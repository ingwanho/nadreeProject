"""Hand approved unfinished work to the shop primary without canceling rentals."""
from sqlalchemy import select

from app.errors import Problem
from app.notifications import record_notification
from app.security import PRIMARY, fingerprint, now, roles


def transfer_approved_work(db, session, spot_id, admin_id):
    reservations, contracts, history = (db.table(name) for name in (
        "MSP_RESERVATION", "MSP_RENTAL_CONTRACT", "MSP_RESERVATION_HISTORY"))
    bookings = session.execute(select(reservations).where(reservations.c.spot_master_id == spot_id)
        .order_by(reservations.c.reservation_id).with_for_update()).mappings().all()
    managers = {}
    for row in session.execute(select(history).where(history.c.reservation_id.in_([b["reservation_id"] for b in bookings]),
            history.c.event_type.in_(("APPROVED", "MANAGER_TRANSFERRED")), history.c.changed_by.is_not(None))
            .order_by(history.c.created_at, history.c.history_id)).mappings():
        managers[row["reservation_id"]] = row["changed_by"]
    owned = [b for b in bookings if managers.get(b["reservation_id"]) == admin_id and
             (b["reservation_status"] in ("APPROVED", "HANDOVER_PENDING", "HANDED_OVER") or
              b["reservation_status"] == "EXPIRED" and b.get("handed_over_at") and b.get("assigned_vehicle_id"))]
    rentals = session.execute(select(contracts).where(contracts.c.reservation_id.in_([b["reservation_id"] for b in owned]))
        .order_by(contracts.c.rental_contract_id).with_for_update()).mappings().all()
    finished = {r["reservation_id"] for r in rentals if r.get("actual_end_time") is not None or r["contract_status"] == "RETURNED"}
    owned = [b for b in owned if b["reservation_id"] not in finished]
    if not owned:
        return 0
    admins, scope = db.table("MSP_ADMIN"), db.table("MSP_ADMIN_SPOT_SCOPE")
    candidates = session.scalars(select(admins.c.admin_id).join(scope, scope.c.admin_id == admins.c.admin_id).where(
        admins.c.primary_spot_master_id == spot_id, admins.c.admin_id != admin_id, admins.c.is_active == 1,
        scope.c.spot_master_id == spot_id, scope.c.access_type == "manage").order_by(admins.c.admin_id))
    recipients = [ident for ident in candidates if PRIMARY in roles(session, db, ident)]
    if len(recipients) != 1:
        raise Problem(409, "PRIMARY_ADMIN_REQUIRED_FOR_HANDOVER")
    recipient = recipients[0]
    for booking in owned:
        ident = booking["reservation_id"]
        session.execute(history.insert().values(reservation_id=ident, event_type="MANAGER_TRANSFERRED",
            previous_reservation_status=booking["reservation_status"], new_reservation_status=booking["reservation_status"],
            previous_vehicle_id=booking["assigned_vehicle_id"], new_vehicle_id=booking["assigned_vehicle_id"],
            previous_assignment_status=booking["vehicle_assignment_status"], new_assignment_status=booking["vehicle_assignment_status"],
            changed_by=recipient, reason="ADMIN_ACCOUNT_DELETED", created_at=now()))
        for rental in rentals:
            if rental["reservation_id"] == ident:
                session.execute(db.table("MSP_RENTAL_CONTRACT_HISTORY").insert().values(
                    rental_contract_id=rental["rental_contract_id"], event_type="MANAGER_TRANSFERRED",
                    previous_contract_status=rental["contract_status"], new_contract_status=rental["contract_status"],
                    changed_by=recipient, reason="ADMIN_ACCOUNT_DELETED", created_at=now()))
        record_notification(db, session, spot_id, "RESERVATION_MANAGER_TRANSFERRED", "RESERVATION", ident,
            "reservation:" + ident + ":handover:" + fingerprint(admin_id)[:24])
    return len(owned)
