"""Run one reconciliation pass with `python -m app.chat_sync` (FCM project only).

Run every 30 seconds with a single scheduler owner. SQL is the durable retry source:
always read the current locked booking, never replay an old open-state event.
"""
import logging

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from google.cloud.firestore_v1.base_query import FieldFilter

from app.chat import FirebaseChat
from app.chat_push import sync_inbox
from app.config import Settings
from app.db import Database
from app.errors import Problem
from app.fcm import FcmSender
from app.security import PRIMARY, GENERAL, SESSION_MARKER, check_contract, now, roles


logger = logging.getLogger(__name__)


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


def run(db, chat, notifier):
    # Exclude manual and second-scheduler execution against this DB as well.
    with db.engine.connect() as connection:
        locked = connection.dialect.name == "mysql"
        name = "nadree:job:chat-sync"
        if locked and connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": name}) != 1:
            logger.info("Chat reconciliation skipped: already running")
            return
        try:
            _run(db, chat, notifier)
        finally:
            if locked:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})


def _run(db, chat, notifier):
    reconcile_sessions(db, chat)
    sync_inbox(db, chat, notifier)
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
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
