import hashlib
import hmac
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text, update

from app.errors import Problem
from app.security import active_spot, check_contract, in_subtree, now, principal

OPEN = ("ON_RENT", "OVERDUE")
MOVABLE = ("PROVISIONAL", "REALLOCATED")


def timezone_for(request):
    return ZoneInfo(request.app.state.settings.business_timezone)


def midnight(request, day):
    try:
        return datetime.combine(day, time.min, timezone_for(request)).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError):
        raise Problem(400, "INVALID_DATE") from None


def day_end(request, day):
    try:
        return midnight(request, day + timedelta(days=1))
    except OverflowError:
        raise Problem(400, "INVALID_DATE") from None


def local_date(request, value):
    return value.replace(tzinfo=timezone.utc).astimezone(timezone_for(request)).date()


def iso(request, value):
    return value.replace(tzinfo=timezone.utc).astimezone(timezone_for(request)).isoformat() if value else None


def context(request, session, *, write=False, representative=False):
    actor = principal(request, session)
    root = active_spot(request, session, actor, representative=representative, lock=write)
    return actor, root


def resolve_spot(request, session, root, code=None, *, lock=False):
    if code is None or code in (root["spot_master_id"], root["unit_code"]):
        return root
    db = request.app.state.db
    t, rent = db.table("MSP_SPOT_MASTER"), db.table("MSP_SPOT_RENT")
    query = select(t).outerjoin(rent, rent.c.spot_master_id == t.c.spot_master_id).where(
        or_(t.c.spot_master_id == code, t.c.unit_code == code, rent.c.legacy_spot_code == code))
    rows = session.execute(query.with_for_update() if lock else query).mappings().all()
    if len(rows) != 1 or not rows[0]["is_active"] or not in_subtree(root, rows[0]):
        raise Problem(404, "SPOT_NOT_FOUND")
    check_contract(request, session, rows[0])
    return rows[0]


def lock_key(session, namespace, value):
    if session.bind.dialect.name != "mysql":
        return
    key = "nadree:" + namespace + ":" + hashlib.sha256(value.encode()).hexdigest()[:40]
    connection = session.connection()
    if connection.scalar(text("SELECT GET_LOCK(:key, 3)"), {"key": key}) != 1:
        raise Problem(409, "RESOURCE_BUSY")
    session.info.setdefault("named_locks", []).append(key)


def rows(session, table, *where):
    return [dict(r) for r in session.execute(select(table).where(*where)).mappings()]


def fleet(request, session, spot, *, model_id=None, lock=False):
    db = request.app.state.db
    v, rv, h = (db.table(n) for n in ("MSP_VEHICLE", "MSP_RENTAL_VEHICLE", "MSP_VEHICLE_SPOT_HISTORY"))
    q = select(v).join(rv, rv.c.vehicle_id == v.c.vehicle_id).join(h, h.c.vehicle_id == v.c.vehicle_id).where(
        h.c.spot_master_id == spot["spot_master_id"], h.c.released_at.is_(None)).order_by(v.c.vehicle_id)
    if model_id:
        q = q.where(rv.c.model_id == model_id)
    vehicles = list(session.execute(q.with_for_update() if lock else q).mappings())
    ids = [v["vehicle_id"] for v in vehicles]
    if not ids:
        return {}
    current = rows(session, h, h.c.vehicle_id.in_(ids), h.c.released_at.is_(None))
    if len(ids) != len(set(ids)) or len(current) != len(ids):
        raise Problem(409, "VEHICLE_SPOT_INCONSISTENT")
    extra = {r["vehicle_id"]: r for r in rows(session, rv, rv.c.vehicle_id.in_(ids))}
    models = db.table("MSP_VEHICLE_MODEL")
    model_rows = {r["model_id"]: r for r in rows(session, models, models.c.model_id.in_({r["model_id"] for r in extra.values()}))}
    states, qrs = {}, {}
    for name, target in [("MSP_VEHICLE_STATUS", states), ("MSP_VEHICLE_QR", qrs)]:
        table = db.table(name)
        target.update({r["vehicle_id"]: r for r in rows(session, table, table.c.vehicle_id.in_(ids))})
    sensor = db.table("MSP_SENSOR")
    sensors = rows(session, sensor, sensor.c.vehicle_id.in_(ids), sensor.c.is_active == 1)
    return {r["vehicle_id"]: {"vehicle": dict(r), "rental": extra[r["vehicle_id"]],
        "model": model_rows.get(extra[r["vehicle_id"]]["model_id"]), "state": states.get(r["vehicle_id"]),
        "qr": qrs.get(r["vehicle_id"]), "sensors": [s for s in sensors if s["vehicle_id"] == r["vehicle_id"]]}
        for r in vehicles}


def by_number(vehicles, number):
    matches = [v for v in vehicles.values() if number == (v["rental"]["plate_number_full"] or v["vehicle"]["plate_number"])]
    if len(matches) != 1:
        raise Problem(404 if not matches else 409, "VEHICLE_NOT_FOUND" if not matches else "VEHICLE_NUMBER_AMBIGUOUS")
    return matches[0]


def contracts_for(request, session, ids):
    t = request.app.state.db.table("MSP_RENTAL_CONTRACT")
    return rows(session, t, t.c.vehicle_id.in_(ids)) if ids else []


def is_open(contract):
    return contract["contract_status"] in OPEN and contract["actual_end_time"] is None


def effective_state(request, item, contracts, at=None):
    at = at or now()
    state = item["state"]
    if state is None:
        return "DISABLED"
    if state["status"] == "MAINTENANCE" and state["maintenance_until"] is not None:
        open_contracts = [c for c in contracts if c["vehicle_id"] == item["vehicle"]["vehicle_id"] and is_open(c)]
        if day_end(request, state["maintenance_until"]) <= at and not open_contracts:
            return "AVAILABLE"
    return state["status"]


def expire_maintenance(request, session, vehicles, contracts):
    t = request.app.state.db.table("MSP_VEHICLE_STATUS")
    for ident, item in vehicles.items():
        if item["state"] and item["state"]["status"] == "MAINTENANCE" and effective_state(request, item, contracts) == "AVAILABLE":
            values = dict(status="AVAILABLE", maintenance_until=None, changed_by=None,
                          status_reason="Maintenance period ended", status_changed_at=now(), updated_at=now())
            session.execute(update(t).where(t.c.vehicle_id == ident, t.c.status == "MAINTENANCE").values(**values))
            item["state"].update(values)


def qr_digest(request, raw):
    if not raw or raw.isspace() or len(raw) > 4096:
        raise Problem(400, "INVALID_QR")
    key = request.app.state.settings.qr_hash_key.get_secret_value()
    if len(key.encode()) < 32:
        raise Problem(503, "QR_VALIDATION_UNAVAILABLE")
    return hmac.new(key.encode(), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_qr(request, session, root, raw, *, lock=False):
    db = request.app.state.db
    qr, h, v = (db.table(n) for n in ("MSP_VEHICLE_QR", "MSP_VEHICLE_SPOT_HISTORY", "MSP_VEHICLE"))
    row = session.execute(select(qr).where(qr.c.qr_code_hash == qr_digest(request, raw))).mappings().first()
    if not row:
        raise Problem(404, "QR_NOT_FOUND")
    memberships = rows(session, h, h.c.vehicle_id == row["vehicle_id"], h.c.released_at.is_(None))
    if not any(r["spot_master_id"] == root["spot_master_id"] for r in memberships):
        raise Problem(404, "QR_NOT_FOUND")
    if len(memberships) != 1:
        raise Problem(500, "QR_STATE_INCONSISTENT")
    query = select(v.c.vehicle_id).where(v.c.vehicle_id == row["vehicle_id"])
    if not session.execute(query.with_for_update() if lock else query).first():
        raise Problem(500, "QR_STATE_INCONSISTENT")
    # Re-read after the same vehicle lock used by issuing, detaching and moving.
    row = session.execute(select(qr).where(qr.c.vehicle_id == row["vehicle_id"])).mappings().one()
    if not hmac.compare_digest(row["qr_code_hash"], qr_digest(request, raw)):
        raise Problem(404, "QR_NOT_FOUND")
    if row["qr_status"] == "EXPIRED" or row["expired_at"] is not None and row["expired_at"] <= now():
        raise Problem(410, "QR_EXPIRED")
    if row["qr_status"] == "INACTIVE":
        raise Problem(409, "QR_INACTIVE")
    if row["qr_status"] != "ACTIVE":
        raise Problem(500, "QR_STATE_INCONSISTENT")
    return row


def action_result(request, actor, state, data):
    return dict(status=True, errorCode=None, message="success", currentState=state,
                changedAt=iso(request, now()), changedBy=actor.admin["admin_id"], data=data)


def page_result(items, page, size, total=None):
    total = len(items) if total is None else total
    return dict(status=True, items=items, page=page, pageSize=size, totalCount=total, hasNext=page * size < total)
