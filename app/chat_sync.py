"""Run one reconciliation pass with `python -m app.chat_sync` (FCM project only).

Run every minute with a single scheduler owner. SQL is the durable retry source:
always read the current locked booking, never replay an old open-state event.
"""
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from google.cloud.firestore_v1.base_query import FieldFilter

from app.chat import FirebaseChat, admin_uid
from app.config import Settings
from app.db import Database
from app.errors import Problem
from app.fcm import FcmSender, _manager_recipients, _queue
from app.notifications import record_notification
from app.security import PRIMARY, GENERAL, SESSION_MARKER, check_contract, fingerprint, now, roles


def reconcile_sessions(db, chat):
    store = chat.store()
    for snapshot in store.db.collection("chatUsers").where(filter=FieldFilter("active", "==", True)).stream():
        row = snapshot.to_dict()
        kind = row["kind"]
        name = "MSP_ADMIN" if kind == "admin" else "MSP_RENTAL_USER"
        key = "admin_id" if kind == "admin" else "uid_token"
        tokens = db.table("MSP_REFRESH_TOKEN" if kind == "admin" else "MSP_RENTAL_USER_REFRESH_TOKEN")
        table = db.table(name)
        with Session(db.engine) as session, session.begin():
            account = session.execute(select(table).where(table.c[key] == row["subjectId"]).with_for_update()).mappings().first()
            token = session.execute(select(tokens).where(tokens.c.token_id == row["businessSessionId"],
                tokens.c[key] == row["subjectId"], tokens.c.revoked_at.is_(None), tokens.c.expires_at > now())).mappings().first()
            valid = bool(account and token)
            if valid and kind == "admin":
                granted = roles(session, db, row["subjectId"])
                valid = bool(account["is_active"] and account["mfa_method"] == "none" and granted & {PRIMARY, GENERAL}
                             and token["user_agent"] == SESSION_MARKER)
                scope, spots = db.table("MSP_ADMIN_SPOT_SCOPE"), db.table("MSP_SPOT_MASTER")
                direct = session.execute(select(spots).join(scope, scope.c.spot_master_id == spots.c.spot_master_id)
                    .where(scope.c.admin_id == row["subjectId"], scope.c.access_type == "manage", spots.c.is_active == 1)).mappings().all()
                active = set()
                for spot in direct:
                    try:
                        check_contract(session, db, spot, chat.settings)
                        active.add(spot["spot_master_id"])
                    except Problem:
                        pass
                valid = valid and active == set(row.get("shopIds", []))
                for shop in active:
                    membership = store.ref(f"chatShops/{shop}/members/{snapshot.id}").get().to_dict() or {}
                    valid = valid and membership.get("canReply") == (PRIMARY in granted)
            if not valid:
                chat.revoke(snapshot.id)


def sync_catalogue(db, chat):
    store = chat.store()
    master, models, vehicles, rental, location = (db.table(n) for n in (
        "MSP_SPOT_MASTER", "MSP_VEHICLE_MODEL", "MSP_VEHICLE", "MSP_RENTAL_VEHICLE", "MSP_VEHICLE_SPOT_HISTORY"))
    with Session(db.engine) as session:
        for spot in session.execute(select(master)).mappings():
            active = bool(spot["is_active"])
            try:
                check_contract(session, db, spot, chat.settings)
            except Problem:
                active = False
            shop_id = spot["spot_master_id"]
            store.ref("chatShops/" + shop_id).set({"active": active, "displayName": spot["spot_name"]}, merge=True)
            query = (select(models.c.model_id, models.c.model_name).join(rental, rental.c.model_id == models.c.model_id)
                .join(vehicles, vehicles.c.vehicle_id == rental.c.vehicle_id)
                .join(location, location.c.vehicle_id == vehicles.c.vehicle_id)
                .where(models.c.is_active == 1, vehicles.c.is_active == 1, rental.c.rental_enabled == 1,
                       location.c.spot_master_id == shop_id, location.c.released_at.is_(None)).distinct())
            products = {r.model_id: r.model_name for r in session.execute(query)} if active else {}
            collection = store.db.collection(f"chatShops/{shop_id}/products")
            for old in collection.stream():
                if old.id not in products:
                    old.reference.set({"active": False}, merge=True)
            for ident, name in products.items():
                collection.document(ident).set({"active": True, "displayName": name})


def sync_inbox(db, chat, notifier):
    store = chat.store()
    for snapshot in store.db.collection("chatPushEvents").where(filter=FieldFilter("inboxSynced", "==", False)).limit(500).stream():
        event = snapshot.to_dict()
        notifications = []
        with Session(db.engine) as session, session.begin():
            inbox = db.table("MSP_RENTAL_NOTIFICATION")
            key = "chat:" + snapshot.id
            exists = session.scalar(select(inbox.c.notification_id).where(inbox.c.event_key == key))
            record_notification(db, session, event["shopId"], "CHAT_MESSAGE", "CHAT", event["roomId"], key)
            if not exists:
                if event["senderKind"] == "customer":
                    recipients = _manager_recipients(db, session, event["shopId"])
                    table_name, key_column = "MSP_ADMIN", "admin_id"
                else:
                    table_name, key_column = "MSP_RENTAL_USER", "uid_token"
                    users = db.table(table_name)
                    row = session.execute(select(users).where(users.c.uid_token == event["customerUid"])).mappings().first()
                    recipients = [{"id": row["uid_token"], "token": row.get("fcm_token"),
                                   "updated_at": row.get("fcm_token_updated_at")}] if row else []
                current = []
                for recipient in recipients:
                    uid = admin_uid(recipient["id"]) if table_name == "MSP_ADMIN" else recipient["id"]
                    user = store.ref("chatUsers/" + uid).get().to_dict() or {}
                    token = store.ref("chatPushTokens/" + uid).get().to_dict() or {}
                    owner = store.ref("chatPushTokenOwners/" + fingerprint(recipient["token"])).get().to_dict() if recipient.get("token") else None
                    if user.get("active") and user.get("expiresAt") > now().replace(tzinfo=timezone.utc) and token.get("sessionId") == user.get("sessionId") and token.get("token") == recipient["token"] and owner == {"uid": uid, "sessionId": user["sessionId"]}:
                        recipient["chat_session_id"] = user["businessSessionId"]
                        current.append(recipient)
                _queue(session, table=table_name, key_column=key_column, recipients=current,
                       event="CHAT_MESSAGE", title="새 채팅 알림", body="새 메시지가 도착했습니다.",
                       data={"eventId": key, "shopId": event["shopId"], "roomId": event["roomId"]})
            notifications = session.info.pop("fcm_notifications", [])
        snapshot.reference.update({"inboxSynced": True})
        notifier.dispatch(db, notifications)


def run(db, chat, notifier):
    reconcile_sessions(db, chat)
    sync_catalogue(db, chat)
    table = db.table("MSP_RESERVATION")
    last = ""
    while True:
        with db.engine.connect() as conn:
            ids = list(conn.scalars(select(table.c.reservation_id).where(table.c.reservation_id > last)
                .order_by(table.c.reservation_id).limit(200)))
        if not ids:
            break
        for ident in ids:
            chat.sync_booking(db, ident)
        last = ids[-1]
    sync_inbox(db, chat, notifier)


if __name__ == "__main__":
    settings = Settings()
    chat = FirebaseChat(settings)
    if not settings.fcm_chat_enabled:
        raise SystemExit("NADREE_FCM_CHAT_ENABLED must be explicitly enabled")
    db, notifier = Database(settings.database_url.get_secret_value()), FcmSender(settings)
    try:
        run(db, chat, notifier)
    finally:
        notifier.close(wait=True)
        db.engine.dispose()
