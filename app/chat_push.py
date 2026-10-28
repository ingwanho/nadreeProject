"""Durable attempts in the existing server-only chatPushEvents documents."""
import logging
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock

from google.cloud.firestore_v1.base_query import FieldFilter
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.chat import admin_uid
from app.fcm import FcmSender, _manager_recipients
from app.notifications import record_notification
from app.errors import Problem
from app.security import PRIMARY, SESSION_MARKER, check_contract, fingerprint, now, roles

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
RETRY_WINDOW = timedelta(hours=1)
_event_locks = [Lock() for _ in range(64)]


def utc(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def eligible_recipients(db, store, event, settings):
    customer_message = event["senderKind"] == "customer"
    table, key = ("MSP_ADMIN", "admin_id") if customer_message else ("MSP_RENTAL_USER", "uid_token")
    with Session(db.engine) as session:
        spots = db.table("MSP_SPOT_MASTER")
        spot = session.execute(select(spots).where(spots.c.spot_master_id == event["shopId"], spots.c.is_active == 1)).mappings().first()
        if not spot:
            return table, key, []
        try:
            check_contract(session, db, spot, settings)
        except Problem:
            return table, key, []
        if customer_message:
            candidates = _manager_recipients(db, session, event["shopId"])
            admins = db.table("MSP_ADMIN")
            sessions = db.table("MSP_REFRESH_TOKEN")
            allowed = []
            for candidate in candidates:
                admin = session.execute(select(admins.c.mfa_method).where(admins.c.admin_id == candidate["id"])).mappings().first()
                if admin and admin["mfa_method"] == "none":
                    allowed.append(dict(candidate, _can_reply=PRIMARY in roles(session, db, candidate["id"])))
            candidates = allowed
        else:
            users = db.table(table)
            row = session.execute(select(users).where(users.c.uid_token == event["customerUid"])).mappings().first()
            candidates = [{"id": row["uid_token"], "token": row.get("fcm_token"),
                           "updated_at": row.get("fcm_token_updated_at")}] if row else []
    recipients, seen = [], set()
    for candidate in candidates:
        token = candidate.get("token")
        if not token or token in seen:
            continue
        uid = admin_uid(candidate["id"]) if customer_message else candidate["id"]
        user = store.ref("chatUsers/" + uid).get().to_dict() or {}
        push = store.ref("chatPushTokens/" + uid).get().to_dict() or {}
        owner = store.ref("chatPushTokenOwners/" + fingerprint(token)).get().to_dict()
        expires = utc(user.get("expiresAt"))
        valid = bool(user.get("active") and expires and expires > utc(now())
                     and user.get("sessionId") and user.get("businessSessionId")
                     and push.get("sessionId") == user["sessionId"] and push.get("token") == token
                     and owner == {"uid": uid, "sessionId": user["sessionId"]})
        if customer_message:
            member = store.ref(f"chatShops/{event['shopId']}/members/{uid}").get().to_dict() or {}
            valid = (valid and event["shopId"] in user.get("shopIds", []) and member.get("active") is True
                     and member.get("canReply") == candidate["_can_reply"])
            with db.engine.connect() as connection:
                valid = valid and bool(connection.scalar(select(sessions.c.token_id).where(
                    sessions.c.token_id == user.get("businessSessionId"), sessions.c.admin_id == candidate["id"],
                    sessions.c.user_agent == SESSION_MARKER)))
        if valid:
            recipients.append(dict(candidate, chat_session_id=user["businessSessionId"], _chat_session_id=user["sessionId"]))
            seen.add(token)
    notification = {"event": "CHAT_MESSAGE", "table": table, "key_column": key, "recipients": recipients}
    return table, key, FcmSender._current_recipients(db, notification)["recipients"]


def recipient_state(item, at):
    return {"subjectId": item["id"], "tokenHash": fingerprint(item["token"]),
            "tokenUpdatedAt": utc(item.get("updated_at")), "businessSessionId": item["chat_session_id"],
            "chatSessionId": item["_chat_session_id"], "status": "pending", "attempts": 0, "nextAttemptAt": at}


def same_context(state, item):
    return bool(item and state["tokenHash"] == fingerprint(item["token"])
                and utc(state.get("tokenUpdatedAt")) == utc(item.get("updated_at"))
                and state["businessSessionId"] == item["chat_session_id"]
                and state["chatSessionId"] == item["_chat_session_id"])


def checkpoint(reference, delivery):
    reference.update({"pushDelivery": delivery, "pushPending": any(row["status"] == "pending" for row in delivery["recipients"])})


@contextmanager
def event_lock(db, event_id):
    name = "nadree:chat-push:" + fingerprint(event_id)[:40]
    local = _event_locks[int(fingerprint(event_id)[:8], 16) % len(_event_locks)]
    if not local.acquire(blocking=False):
        yield False
        return
    try:
        with db.engine.connect() as connection:
            mysql = connection.dialect.name == "mysql"
            if mysql and connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": name}) != 1:
                yield False
                return
            try:
                yield True
            finally:
                if mysql:
                    connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
    finally:
        local.release()


def dispatch_event(db, chat, notifier, event_id, counters=None):
    """Both HTTP and the scheduler must enter through this per-event lock."""
    if counters is None:
        counters = Counter()
    with event_lock(db, event_id) as acquired:
        if not acquired:
            counters["busy"] += 1
            return "busy"
        store = chat.store()
        # A scheduler's query snapshot can predate another caller's completion.
        snapshot = store.ref("chatPushEvents/" + event_id).get()
        event = snapshot.to_dict()
        if event is None:
            return "missing"
        if event.get("inboxSynced") is True and event.get("pushPending") is not True:
            return "completed"
        process_event(db, store, notifier, snapshot, counters, chat.settings)
        latest = snapshot.reference.get().to_dict() or {}
        return "pending" if latest.get("pushPending") is True else "completed"


def process_event(db, store, notifier, snapshot, counters, settings):
    event, at = snapshot.to_dict(), utc(now())
    delivery = event.get("pushDelivery")
    if delivery is None:
        _, _, recipients = eligible_recipients(db, store, event, settings)
        delivery = {"version": 1, "createdAt": at,
                    "expiresAt": (utc(event.get("createdAt")) or at) + RETRY_WINDOW,
                    "recipients": [recipient_state(item, at) for item in recipients]}
        # Freeze recipients BEFORE SQL commit and before any external send.
        checkpoint(snapshot.reference, delivery)
    if delivery.get("version") != 1:
        raise ValueError("Unsupported chat delivery state")
    with Session(db.engine) as session, session.begin():
        record_notification(db, session, event["shopId"], "CHAT_MESSAGE", "CHAT", event["roomId"], "chat:" + snapshot.id)
    if event.get("inboxSynced") is not True:
        # SQL deduplication must not suppress a push if this write fails.
        snapshot.reference.update({"inboxSynced": True})
    due = [row for row in delivery["recipients"] if row["status"] == "pending"
           and (utc(row.get("nextAttemptAt")) or at) <= at]
    if not due:
        return
    table, key, candidates = eligible_recipients(db, store, event, settings)
    current, sending = {item["id"]: item for item in candidates}, []
    for state in due:
        item = current.get(state["subjectId"])
        if not same_context(state, item):
            state.update(status="skipped", lastErrorCode="SECURITY_CONTEXT_CHANGED")
            counters["skipped"] += 1
        elif at >= utc(delivery["expiresAt"]) or state["attempts"] >= MAX_ATTEMPTS:
            state.update(status="failed", lastErrorCode="RETRY_LIMIT_REACHED")
            counters["failed"] += 1
        else:
            state["attempts"] += 1
            state["nextAttemptAt"] = at + timedelta(seconds=min(30 * 2 ** (state["attempts"] - 1), 300))
            sending.append(item)
    checkpoint(snapshot.reference, delivery)
    if not sending:
        return
    result = notifier.deliver_chat_once(db, {"event": "CHAT_MESSAGE", "table": table, "key_column": key,
        "recipients": sending, "title": "새 채팅 알림", "body": "새 메시지가 도착했습니다.",
        "data": {"eventId": "chat:" + snapshot.id, "shopId": event["shopId"], "roomId": event["roomId"]}})
    accepted = {item["id"] for item in result["accepted"]}
    failed = {item["id"] for item in result["failed"] + result["invalid"]}
    skipped, sent_ids = {item["id"] for item in result["skipped"]}, {item["id"] for item in sending}
    for state in due:
        if state["status"] != "pending" or state["subjectId"] not in sent_ids:
            continue
        if state["subjectId"] in accepted:
            state.update(status="accepted", acceptedAt=utc(now()), lastErrorCode=None)
            counters["accepted"] += 1
        elif state["subjectId"] in failed:
            state.update(status="failed", lastErrorCode="PERMANENT_PROVIDER_REJECTION")
            counters["failed"] += 1
        elif state["subjectId"] in skipped:
            state.update(status="skipped", lastErrorCode="SECURITY_CONTEXT_CHANGED")
            counters["skipped"] += 1
        else:
            state["lastErrorCode"] = "TRANSIENT_PROVIDER_ERROR"
            delay = result.get("retry_after")
            if isinstance(delay, (int, float)) and 0 <= delay <= 3600:
                state["nextAttemptAt"] = max(state["nextAttemptAt"], at + timedelta(seconds=delay))
            if state["attempts"] >= MAX_ATTEMPTS:
                state.update(status="failed", lastErrorCode="RETRY_LIMIT_REACHED")
                counters["failed"] += 1
            else:
                counters["retry"] += 1
    checkpoint(snapshot.reference, delivery)


def sync_inbox(db, chat, notifier):
    store, counters, seen = chat.store(), Counter(), set()
    # Legacy completed events without pushPending are never replayed.
    for field, value in (("pushPending", True), ("inboxSynced", False)):
        query = store.db.collection("chatPushEvents").where(filter=FieldFilter(field, "==", value)).limit(500)
        for snapshot in query.stream():
            if snapshot.id in seen:
                continue
            seen.add(snapshot.id)
            counters["events"] += 1
            try:
                dispatch_event(db, chat, notifier, snapshot.id, counters)
            except Exception as exc:
                counters["deferred"] += 1
                logger.warning("Chat push event deferred: %s", type(exc).__name__)
    logger.info("Chat push pass: events=%d accepted=%d retry=%d skipped=%d failed=%d deferred=%d",
                *(counters[key] for key in ("events", "accepted", "retry", "skipped", "failed", "deferred")))
    return dict(counters)
