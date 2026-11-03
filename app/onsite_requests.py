"""Durable onsite outcomes. A closed request key can never create a booking."""
import hashlib
import json

from sqlalchemy import select, text, update
from sqlalchemy.exc import NoSuchTableError

from app.errors import Problem
from app.security import now

TABLE = "MSP_RENTAL_ONSITE_REQUEST"


def require_schema(db):
    try:
        table = db.table(TABLE)
    except NoSuchTableError:
        raise Problem(503, "ONSITE_REQUEST_SCHEMA_UPDATE_REQUIRED") from None
    if not {"uid_token", "client_request_id", "request_fingerprint", "request_state",
            "reservation_id", "error_code", "http_status", "created_at", "updated_at"}.issubset(table.c.keys()):
        raise Problem(503, "ONSITE_REQUEST_SCHEMA_UPDATE_REQUIRED")
    return table


def outcome(key, state, *, code=None):
    final = state in ("ACCEPTED", "REJECTED")
    return {"clientRequestId": key, "requestStatus": state, "requestFinal": final,
            "retrySameRequest": state != "REJECTED", "canStartNewRequest": state == "REJECTED",
            **({"errorCode": code} if code else {})}


def fingerprint(body):
    # Neither the QR original nor the signed quote is persisted in this table.
    value = {"qrCode": body.qrCode.get_secret_value(), "returnDate": str(body.returnDate),
             "quoteToken": body.quoteToken.get_secret_value()}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def lock_name(uid, key):
    return "nadree:onsite:" + hashlib.sha256((uid + ":" + key).encode()).hexdigest()[:40]


def try_lock(session, uid, key):
    if session.bind.dialect.name != "mysql":
        return True
    name = lock_name(uid, key)
    if session.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": name}) != 1:
        return False
    session.info.setdefault("named_locks", []).append(name)
    return True


def processing(session, uid, key):
    return (session.bind.dialect.name == "mysql"
            and session.scalar(text("SELECT IS_USED_LOCK(:name)"), {"name": lock_name(uid, key)}) is not None)


def find(session, table, uid, key):
    return session.execute(select(table).where(table.c.uid_token == uid,
        table.c.client_request_id == key)).mappings().first()


def accepted_id(db, session, uid, key):
    table = db.table("MSP_RESERVATION")
    return session.scalar(select(table.c.reservation_id).where(table.c.uid_token == uid,
        table.c.client_request_id == key))


def start(session, table, uid, key, digest, record):
    if record and record["request_state"] == "REJECTED":
        raise Problem(record["http_status"], record["error_code"], request_outcome=outcome(
            key, "REJECTED", code=record["error_code"]))
    if record and record["request_state"] == "ACCEPTED":
        raise Problem(503, "ONSITE_RESULT_UNAVAILABLE", request_outcome=outcome(key, "UNKNOWN"))
    if record and record["request_fingerprint"] != digest:
        raise Problem(409, "REQUEST_KEY_REUSED", request_outcome={**outcome(key, "UNKNOWN"), "retrySameRequest": False})
    at = now()
    if record:
        session.execute(update(table).where(table.c.uid_token == uid, table.c.client_request_id == key)
                        .values(updated_at=at))
    else:
        session.execute(table.insert().values(uid_token=uid, client_request_id=key,
            request_fingerprint=digest, request_state="PROCESSING", created_at=at, updated_at=at))
    # Connection-owned locks remain held across this checkpoint.
    session.commit()


def accept(session, table, uid, key, ident):
    session.execute(update(table).where(table.c.uid_token == uid, table.c.client_request_id == key)
        .values(request_state="ACCEPTED", reservation_id=ident, error_code=None, http_status=None, updated_at=now()))


def reject(session, table, uid, key, error):
    session.rollback()
    if error.status >= 500 or error.code in ("RESOURCE_BUSY", "RATE_LIMITED"):
        error.request_outcome = outcome(key, "UNKNOWN")
        raise error
    session.execute(update(table).where(table.c.uid_token == uid, table.c.client_request_id == key)
        .values(request_state="REJECTED", reservation_id=None, error_code=error.code,
                http_status=error.status, updated_at=now()))
    session.commit()
    error.request_outcome = outcome(key, "REJECTED", code=error.code)
    raise error


def close(session, table, uid, key, record):
    values = dict(request_state="REJECTED", reservation_id=None, error_code="ONSITE_REQUEST_CLOSED",
                  http_status=409, updated_at=now())
    if record:
        session.execute(update(table).where(table.c.uid_token == uid, table.c.client_request_id == key).values(**values))
    else:
        session.execute(table.insert().values(uid_token=uid, client_request_id=key, created_at=now(), **values))
