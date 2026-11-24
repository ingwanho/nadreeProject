"""Customer receipt policy; a physical handover hold survives reservation expiry."""
from sqlalchemy import select, update

from app.errors import Problem
from app.rental_common import day_end, iso, local_date
from app.security import now

PENDING = "HANDOVER_PENDING"
HOLD_PREFIX = "CUSTOMER_RECEIPT:"


def require_schema(db):
    if not {"client_request_id", "handed_over_at", "receipt_deadline_at"}.issubset(db.table("MSP_RESERVATION").c.keys()):
        raise Problem(503, "RECEIPT_SCHEMA_UPDATE_REQUIRED")


def is_onsite(reservation):
    return ((reservation or {}).get("required_criteria_json") or {}).get("requestType") in ("ONSITE", "WALK_IN")


def hold_reason(reservation_id):
    return HOLD_PREFIX + reservation_id


def require_no_hold(item):
    if item.get("recoveryReservationIds") or ((item.get("state") or {}).get("status_reason") or "").startswith(HOLD_PREFIX):
        raise Problem(409, "VEHICLE_RECEIPT_HOLD")


def view(request, reservation, contract=None):
    reservation = reservation or {}
    deadline = day_end(request, local_date(request, reservation["end_datetime"])) if reservation.get("end_datetime") else reservation.get("receipt_deadline_at")
    pending = reservation.get("reservation_status") == PENDING
    can_receive = bool(pending and deadline and now() < deadline)
    required = bool(reservation) and (reservation.get("required_criteria_json") or {}).get("handoverFlowVersion") != 2
    if reservation.get("reservation_status") in ("HANDED_OVER", "RETURNED") and not reservation.get("handed_over_at"):
        required = False
    from app.booking_lifecycle import needs_recovery as recovery_required
    needs_recovery = recovery_required(request.app.state.settings, reservation, now())
    return {"requestType": "WALK_IN" if is_onsite(reservation) else "ADVANCE",
            "requestDeadline": iso(request, deadline) if is_onsite(reservation) else None,
            "latePickupWarning": bool(reservation.get("reservation_status") in ("REQUESTED", "APPROVED", PENDING)
                and reservation.get("start_datetime") and local_date(request, reservation["start_datetime"]) < local_date(request, now())
                and deadline and now() < deadline),
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
    deadline = day_end(request, local_date(request, reservation["end_datetime"]))
    criteria = dict(reservation.get("required_criteria_json") or {}, customerReceiptRequired=True)
    qr = db.table("MSP_VEHICLE_QR")
    criteria["receiptQrDigest"] = session.scalar(select(qr.c.qr_code_hash).where(qr.c.vehicle_id == vehicle_id))
    values = dict(reservation_status=PENDING, assigned_vehicle_id=vehicle_id,
                  vehicle_assignment_status="LOCKED", vehicle_assigned_at=at,
                  handed_over_at=at, receipt_deadline_at=deadline,
                  required_criteria_json=criteria, updated_at=at)
    session.execute(update(table).where(table.c.reservation_id == reservation["reservation_id"]).values(**values))
    session.execute(update(state).where(state.c.vehicle_id == vehicle_id).values(
        status="DISABLED", state_version=state.c.state_version + 1, operation_id=None, status_reason=hold_reason(reservation["reservation_id"]),
        status_changed_at=at, changed_by=admin_id, updated_at=at))
    from app.availability import reservation_history
    from app.fcm import queue_receipt_required
    reservation_history(request, session, reservation, values, PENDING, admin_id)
    queue_receipt_required(db, session, reservation["uid_token"], reservation["reservation_id"], deadline)
    return {**reservation, **values}


def expire_receipts(db, settings, at=None):
    """Catch up date transitions under the same shop lock as API writes."""
    from sqlalchemy.orm import Session
    from app.booking_lifecycle import reconcile
    at = at or now()
    count = 0
    with Session(db.engine) as session, session.begin():
        master = db.table("MSP_SPOT_MASTER")
        for ident in session.scalars(select(master.c.spot_master_id).order_by(master.c.spot_master_id).with_for_update()):
            count += reconcile(db, settings, session, at, spot_id=ident)
    return count
