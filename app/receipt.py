"""Customer receipt policy; a physical handover hold survives reservation expiry."""
from sqlalchemy import and_, or_, select, update

from app.errors import Problem
from app.rental_common import day_end, iso, local_date
from app.security import now

PENDING = "HANDOVER_PENDING"
HOLD_PREFIX = "CUSTOMER_RECEIPT:"


def require_schema(db):
    if not {"client_request_id", "handed_over_at", "receipt_deadline_at"}.issubset(db.table("MSP_RESERVATION").c.keys()):
        raise Problem(503, "RECEIPT_SCHEMA_UPDATE_REQUIRED")


def is_onsite(reservation):
    return ((reservation or {}).get("required_criteria_json") or {}).get("requestType") == "ONSITE"


def hold_reason(reservation_id):
    return HOLD_PREFIX + reservation_id


def require_no_hold(item):
    if ((item.get("state") or {}).get("status_reason") or "").startswith(HOLD_PREFIX):
        raise Problem(409, "VEHICLE_RECEIPT_HOLD")


def view(request, reservation, contract=None):
    reservation = reservation or {}
    deadline = reservation.get("receipt_deadline_at")
    pending = reservation.get("reservation_status") == PENDING
    can_receive = bool(pending and deadline and now() < deadline)
    required = bool(reservation)
    if reservation.get("reservation_status") in ("HANDED_OVER", "RETURNED") and not reservation.get("handed_over_at"):
        required = False
    needs_recovery = bool(reservation.get("handed_over_at") and
        (reservation.get("reservation_status") == "EXPIRED" or pending and deadline and now() >= deadline))
    return {"requestType": "ONSITE" if is_onsite(reservation) else "ADVANCE",
            "requestDeadline": iso(request, reservation.get("hold_expires_at")) if is_onsite(reservation) else None,
            "customerReceiptRequired": required,
            "handedOverAt": iso(request, reservation.get("handed_over_at")),
            "receiptDeadline": iso(request, deadline),
            "receivedAt": iso(request, (contract or {}).get("actual_start_time")) if reservation.get("handed_over_at") else None,
            "canReceive": can_receive,
            "receiptBlockedReason": None if can_receive else "RECEIPT_DEADLINE_EXPIRED" if needs_recovery else "NOT_AWAITING_RECEIPT",
            "vehicleRecoveryRequired": needs_recovery}


def prepare(request, session, reservation, vehicle_id, admin_id):
    db = request.app.state.db
    require_schema(db)
    table, state = db.table("MSP_RESERVATION"), db.table("MSP_VEHICLE_STATUS")
    at = now()
    deadline = day_end(request, local_date(request, at))
    criteria = dict(reservation.get("required_criteria_json") or {}, customerReceiptRequired=True)
    qr = db.table("MSP_VEHICLE_QR")
    criteria["receiptQrDigest"] = session.scalar(select(qr.c.qr_code_hash).where(qr.c.vehicle_id == vehicle_id))
    values = dict(reservation_status=PENDING, assigned_vehicle_id=vehicle_id,
                  vehicle_assignment_status="LOCKED", vehicle_assigned_at=at,
                  handed_over_at=at, receipt_deadline_at=deadline,
                  required_criteria_json=criteria, updated_at=at)
    session.execute(update(table).where(table.c.reservation_id == reservation["reservation_id"]).values(**values))
    session.execute(update(state).where(state.c.vehicle_id == vehicle_id).values(
        status="DISABLED", status_reason=hold_reason(reservation["reservation_id"]),
        status_changed_at=at, changed_by=admin_id, updated_at=at))
    from app.availability import reservation_history
    from app.fcm import queue_receipt_required
    reservation_history(request, session, reservation, values, PENDING, admin_id)
    queue_receipt_required(db, session, reservation["uid_token"], reservation["reservation_id"], deadline)
    return {**reservation, **values}


def expire_receipts(db, settings, at=None):
    """No provider calls or automatic release of a physically handed-over vehicle."""
    from sqlalchemy.orm import Session
    at = at or now()
    require_schema(db)
    table, history = db.table("MSP_RESERVATION"), db.table("MSP_RESERVATION_HISTORY")
    count = 0
    with Session(db.engine) as session, session.begin():
        records = session.execute(select(table).where(or_(
            and_(table.c.reservation_status == PENDING, table.c.receipt_deadline_at <= at),
            and_(table.c.reservation_status.in_(("REQUESTED", "APPROVED")), table.c.hold_expires_at <= at)))
                                  .with_for_update()).mappings().all()
        for row in records:
            pending = row["reservation_status"] == PENDING
            deadline = row["receipt_deadline_at"] if pending else row["hold_expires_at"] if is_onsite(row) else None
            if not deadline or at < deadline:
                continue
            values = {"reservation_status": "EXPIRED", "updated_at": at}
            if not pending:
                values.update(vehicle_assignment_status="RELEASED", assigned_vehicle_id=None, vehicle_assigned_at=None)
            session.execute(update(table).where(table.c.reservation_id == row["reservation_id"]).values(**values))
            session.execute(history.insert().values(reservation_id=row["reservation_id"], event_type="EXPIRED",
                previous_reservation_status=row["reservation_status"], new_reservation_status="EXPIRED",
                previous_vehicle_id=row["assigned_vehicle_id"], new_vehicle_id=row["assigned_vehicle_id"] if pending else None,
                previous_assignment_status=row["vehicle_assignment_status"],
                new_assignment_status=row["vehicle_assignment_status"] if pending else "RELEASED",
                changed_by=None, reason="Receipt deadline exceeded" if pending else "Onsite request day ended",
                details={"actorType": "SYSTEM", "vehicleRecoveryRequired": pending}, created_at=at))
            from app.notifications import record_notification
            record_notification(db, session, row["spot_master_id"], "RESERVATION_EXPIRED", "RESERVATION",
                                row["reservation_id"], "reservation:" + row["reservation_id"] + ":EXPIRED")
            count += 1
    # SQL is authoritative; existing reconciliation retries chat closure.
    return count
