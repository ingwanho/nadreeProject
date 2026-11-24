"""Bali calendar-day transitions; no physical vehicle is released by expiry."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, select, update


def cutoff(settings, at):
    zone = ZoneInfo(settings.business_timezone)
    day = at.replace(tzinfo=timezone.utc).astimezone(zone).date()
    return datetime.combine(day, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)


def effective_status(settings, row, at):
    status = row.get("reservation_status")
    end = row.get("end_datetime")
    if end is not None and end < cutoff(settings, at):
        if status == "REQUESTED":
            return "NO_RESPONSE"
        if status in ("APPROVED", "HANDOVER_PENDING"):
            return "EXPIRED"
    return status


def status_expression(settings, table, at):
    ended = table.c.end_datetime < cutoff(settings, at)
    return case((and_(ended, table.c.reservation_status == "REQUESTED"), "NO_RESPONSE"),
                (and_(ended, table.c.reservation_status.in_(("APPROVED", "HANDOVER_PENDING"))), "EXPIRED"),
                else_=table.c.reservation_status)


def needs_recovery(settings, row, at):
    status = effective_status(settings, row, at)
    return bool(status == "EXPIRED" and row.get("assigned_vehicle_id") and (
        row["reservation_status"] in ("APPROVED", "HANDOVER_PENDING") or row.get("handed_over_at") or
        (row.get("required_criteria_json") or {}).get("vehicleRecoveryRequired")))


def projected(settings, row, at):
    if row is None:
        return None
    result = dict(row)
    if needs_recovery(settings, row, at):
        result["required_criteria_json"] = dict(row.get("required_criteria_json") or {}, vehicleRecoveryRequired=True)
    result["reservation_status"] = effective_status(settings, row, at)
    return result


def reconcile(db, settings, session, at, *, spot_id=None, backfill=False):
    """Caller holds the shop lock; job locks shops before their bookings."""
    from app.receipt import hold_reason
    from app.handover import expire_for_reservation
    r, history = db.table("MSP_RESERVATION"), db.table("MSP_RESERVATION_HISTORY")
    where = r.c.reservation_status.in_(("REQUESTED", "APPROVED", "HANDOVER_PENDING"))
    if backfill:
        where |= r.c.reservation_status == "EXPIRED"
    if spot_id:
        where &= r.c.spot_master_id == spot_id
    records = session.execute(select(r).where(where).order_by(r.c.reservation_id).with_for_update()).mappings().all()
    changed = 0
    for row in records:
        target = effective_status(settings, row, at)
        if backfill and row["reservation_status"] == "EXPIRED":
            events = list(session.execute(select(history).where(history.c.reservation_id == row["reservation_id"])
                .order_by(history.c.created_at, history.c.history_id)).mappings())
            expiry = [e for e in events if e["new_reservation_status"] == "EXPIRED"]
            if not row.get("handed_over_at") and expiry and expiry[-1]["previous_reservation_status"] == "REQUESTED" and not any(
                    e["event_type"] == "APPROVED" for e in events):
                target = "NO_RESPONSE"
        if target == row["reservation_status"]:
            continue
        criteria = dict(row.get("required_criteria_json") or {})
        values = {"reservation_status": target, "updated_at": at}
        recovery = target == "EXPIRED" and bool(row.get("assigned_vehicle_id"))
        if recovery:
            criteria["vehicleRecoveryRequired"] = True
            values.update(required_criteria_json=criteria, vehicle_assignment_status="LOCKED")
            state = db.table("MSP_VEHICLE_STATUS")
            session.execute(update(state).where(state.c.vehicle_id == row["assigned_vehicle_id"],
                state.c.status == "AVAILABLE").values(status="DISABLED",
                state_version=state.c.state_version + 1, operation_id=None,
                status_reason=hold_reason(row["reservation_id"]), status_changed_at=at, updated_at=at))
        else:
            values.update(vehicle_assignment_status="RELEASED", assigned_vehicle_id=None, vehicle_assigned_at=None)
        session.execute(update(r).where(r.c.reservation_id == row["reservation_id"]).values(**values))
        expire_for_reservation(db, session, row, at)
        session.execute(history.insert().values(reservation_id=row["reservation_id"], event_type=target,
            previous_reservation_status=row["reservation_status"], new_reservation_status=target,
            previous_vehicle_id=row["assigned_vehicle_id"], new_vehicle_id=values.get("assigned_vehicle_id", row["assigned_vehicle_id"]),
            previous_assignment_status=row["vehicle_assignment_status"],
            new_assignment_status=values["vehicle_assignment_status"], changed_by=None,
            reason="RENTAL_END_DATE_PASSED", details={"actorType": "SYSTEM", "vehicleRecoveryRequired": recovery}, created_at=at))
        changed += 1
    c = db.table("MSP_RENTAL_CONTRACT")
    today = cutoff(settings, at).replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.business_timezone)).date()
    condition = (c.c.contract_status == "ON_RENT") & c.c.actual_end_time.is_(None) & (c.c.planned_end_date < today)
    if spot_id:
        condition &= c.c.pickup_spot_master_id == spot_id
    contracts = session.execute(select(c).where(condition).order_by(c.c.rental_contract_id).with_for_update()).mappings()
    for contract in contracts:
        session.execute(update(c).where(c.c.rental_contract_id == contract["rental_contract_id"]).values(contract_status="OVERDUE", updated_at=at))
        session.execute(db.table("MSP_RENTAL_CONTRACT_HISTORY").insert().values(
            rental_contract_id=contract["rental_contract_id"], event_type="OVERDUE", previous_contract_status="ON_RENT",
            new_contract_status="OVERDUE", reason="RENTAL_END_DATE_PASSED", changed_by=None, created_at=at))
        changed += 1
    return changed
