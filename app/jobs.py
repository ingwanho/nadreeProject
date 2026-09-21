"""Idempotent maintenance, payment-expiry, and inventory jobs.

These jobs are intentionally explicit CLI entry points. The API process does not
start a second scheduler, so one cron/systemd owner can run them in production.
"""

import argparse
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Database
from app.fcm import (FcmSender, queue_payment_deadline_expired,
                     queue_payment_deadline_reminder)

OPEN_CONTRACTS = ("ON_RENT", "OVERDUE")
PAYMENT_DEADLINE = timedelta(days=3)
PAYMENT_REMINDERS = ((2, timedelta(days=1)), (1, timedelta(days=2)))


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _local_day(settings, at):
    return at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.business_timezone)).date()


def _midnight(settings, day):
    return datetime.combine(day, time.min, ZoneInfo(settings.business_timezone)).astimezone(timezone.utc).replace(tzinfo=None)


def expire_maintenance(db, settings, at=None):
    """Release ended maintenance after the local end date, preserving open rentals."""
    at = at or _utc_now()
    today = _local_day(settings, at)
    state, contracts = db.table("MSP_VEHICLE_STATUS"), db.table("MSP_RENTAL_CONTRACT")
    changed = 0
    with Session(db.engine) as session, session.begin():
        rows = session.execute(select(state).where(state.c.status == "MAINTENANCE",
                                                    state.c.maintenance_until < today).with_for_update()).mappings().all()
        for row in rows:
            open_rental = session.execute(select(contracts.c.rental_contract_id).where(
                contracts.c.vehicle_id == row["vehicle_id"], contracts.c.contract_status.in_(OPEN_CONTRACTS),
                contracts.c.actual_end_time.is_(None))).first()
            if open_rental:
                continue
            result = session.execute(update(state).where(state.c.vehicle_id == row["vehicle_id"],
                state.c.status == "MAINTENANCE", state.c.maintenance_until == row["maintenance_until"])
                .values(status="AVAILABLE", maintenance_until=None, changed_by=None,
                        status_reason="Maintenance period ended", status_changed_at=at, updated_at=at))
            changed += result.rowcount
    return changed


def expire_unpaid_payments(db, settings, at=None, notifier=None):
    """Send payment deadline reminders and expire unpaid approved reservations."""
    at = at or _utc_now()
    payments = db.table("MSP_RENTAL_PAYMENT")
    reservations, history = db.table("MSP_RESERVATION"), db.table("MSP_RESERVATION_HISTORY")
    contracts = db.table("MSP_RENTAL_CONTRACT")
    expired = 0
    notifications = []
    with Session(db.engine) as session, session.begin():
        rows = session.execute(select(reservations).where(
            reservations.c.reservation_status == "APPROVED").with_for_update()).mappings().all()
        reservation_ids = [row["reservation_id"] for row in rows]
        if not reservation_ids:
            return 0
        linked_reservations = set(session.scalars(select(contracts.c.reservation_id).where(
            contracts.c.reservation_id.in_(reservation_ids))).all())
        history_rows = session.execute(select(history.c.reservation_id, history.c.event_type, history.c.created_at).where(
            history.c.reservation_id.in_(reservation_ids))).mappings().all()
        approval_at = {}
        sent_events = {}
        for event in history_rows:
            sent_events.setdefault(event["reservation_id"], set()).add(event["event_type"])
            if event["event_type"] == "APPROVED":
                approval_at.setdefault(event["reservation_id"], event["created_at"])
        for reservation in rows:
            reservation_id = reservation["reservation_id"]
            if reservation_id in linked_reservations:
                continue
            approved_at = approval_at.get(reservation_id) or reservation.get("updated_at") or reservation.get("created_at")
            if approved_at is None:
                continue
            payment_rows = session.execute(select(payments).where(
                payments.c.reservation_id == reservation_id,
                payments.c.payment_environment == settings.paypal_environment).order_by(payments.c.payment_id)
                .with_for_update()).mappings().all()
            statuses = {payment["payment_status"] for payment in payment_rows}
            if statuses & {"PAID", "PARTIALLY_REFUNDED", "REFUNDED"} or "PENDING" in statuses:
                continue
            deadline = approved_at + PAYMENT_DEADLINE
            events = sent_events.setdefault(reservation_id, set())
            if at >= deadline:
                for payment in payment_rows:
                    if payment["payment_status"] == "CREATED":
                        session.execute(update(payments).where(
                            payments.c.payment_id == payment["payment_id"], payments.c.payment_status == "CREATED")
                            .values(payment_status="CANCELED", refund_status="NOT_REQUIRED",
                                    refund_reason="Payment deadline exceeded", updated_at=at))
                values = {"reservation_status": "EXPIRED", "vehicle_assignment_status": "RELEASED",
                          "assigned_vehicle_id": None, "vehicle_assigned_at": None, "updated_at": at}
                result = session.execute(update(reservations).where(
                    reservations.c.reservation_id == reservation_id,
                    reservations.c.reservation_status == "APPROVED").values(**values))
                if result.rowcount != 1:
                    continue
                session.execute(history.insert().values(reservation_id=reservation_id, event_type="EXPIRED",
                    previous_reservation_status="APPROVED", new_reservation_status="EXPIRED",
                    previous_vehicle_id=reservation["assigned_vehicle_id"], new_vehicle_id=None,
                    previous_assignment_status=reservation["vehicle_assignment_status"], new_assignment_status="RELEASED",
                    reason="Payment deadline exceeded", changed_by="nadree-job", created_at=at))
                queue_payment_deadline_expired(db, session, reservation["uid_token"], reservation_id)
                events.add("EXPIRED")
                expired += 1
                continue
            for days_remaining, offset in PAYMENT_REMINDERS:
                event_name = "PAYMENT_DEADLINE_" + str(days_remaining) + "_DAY"
                if at < approved_at + offset or event_name in events:
                    continue
                session.execute(history.insert().values(
                    reservation_id=reservation_id, event_type=event_name,
                    previous_reservation_status="APPROVED", new_reservation_status="APPROVED",
                    previous_vehicle_id=reservation["assigned_vehicle_id"], new_vehicle_id=reservation["assigned_vehicle_id"],
                    previous_assignment_status=reservation["vehicle_assignment_status"],
                    new_assignment_status=reservation["vehicle_assignment_status"],
                    reason="Payment deadline reminder", changed_by="nadree-job", created_at=at))
                queue_payment_deadline_reminder(db, session, reservation["uid_token"], reservation_id,
                                                days_remaining, deadline)
                events.add(event_name)
        notifications = session.info.pop("fcm_notifications", [])
    if notifications:
        (notifier or FcmSender(settings)).dispatch(db, notifications)
    return expired


def rebuild_daily_inventory(db, settings, days=None, at=None):
    """Rebuild the next horizon from current fleet, reservations, rentals and status."""
    at = at or _utc_now()
    horizon = days or settings.inventory_horizon_days
    first = _local_day(settings, at)
    spots, vehicles, rentals, histories, models = (db.table(name) for name in
        ("MSP_SPOT_MASTER", "MSP_VEHICLE", "MSP_RENTAL_VEHICLE", "MSP_VEHICLE_SPOT_HISTORY", "MSP_VEHICLE_MODEL"))
    states, reservations, contracts, inventory = (db.table(name) for name in
        ("MSP_VEHICLE_STATUS", "MSP_RESERVATION", "MSP_RENTAL_CONTRACT", "MSP_MODEL_DAILY_INVENTORY"))
    written = 0
    with Session(db.engine) as session, session.begin():
        fleet_query = select(histories.c.spot_master_id, vehicles.c.vehicle_id, rentals.c.model_id,
            states.c.status, states.c.maintenance_until, states.c.status_changed_at).select_from(
                histories.join(vehicles, vehicles.c.vehicle_id == histories.c.vehicle_id)
                .join(rentals, rentals.c.vehicle_id == vehicles.c.vehicle_id)
                .join(models, models.c.model_id == rentals.c.model_id)
                .outerjoin(states, states.c.vehicle_id == vehicles.c.vehicle_id)
            ).where(histories.c.released_at.is_(None), vehicles.c.is_active == 1,
                    rentals.c.rental_enabled == 1, models.c.is_active == 1)
        fleet_rows = session.execute(fleet_query).mappings().all()
        # Keep only active spots; the history table can contain a stale assignment.
        active_spots = set(session.scalars(select(spots.c.spot_master_id).where(spots.c.is_active == 1)))
        fleet_rows = [dict(row) for row in fleet_rows if row["spot_master_id"] in active_spots]
        by_key = {}
        for row in fleet_rows:
            by_key.setdefault((row["spot_master_id"], row["model_id"]), []).append(row)
        approved = session.execute(select(reservations).where(
            reservations.c.reservation_status.in_(("APPROVED", "HANDED_OVER")))).mappings().all()
        active_contracts = session.execute(select(contracts).where(
            contracts.c.contract_status.in_(OPEN_CONTRACTS))).mappings().all()
        for (spot_id, model_id), fleet_items in by_key.items():
            total = len(fleet_items)
            ids = {row["vehicle_id"] for row in fleet_items}
            for offset in range(horizon):
                target = first + timedelta(days=offset)
                begin, end = _midnight(settings, target), _midnight(settings, target + timedelta(days=1))
                blocked = {row["vehicle_id"] for row in fleet_items if row["status"] == "DISABLED"}
                blocked.update(row["vehicle_id"] for row in fleet_items
                              if row["status"] == "MAINTENANCE" and row["maintenance_until"] and row["maintenance_until"] >= target)
                for reservation in approved:
                    if reservation["spot_master_id"] != spot_id or reservation["model_id"] != model_id:
                        continue
                    if reservation["start_datetime"] < end and reservation["end_datetime"] >= begin:
                        if reservation["assigned_vehicle_id"] in ids:
                            blocked.add(reservation["assigned_vehicle_id"])
                for contract in active_contracts:
                    if contract["vehicle_id"] not in ids or contract["actual_start_time"] >= end:
                        continue
                    if contract["actual_end_time"] is None or contract["actual_end_time"] > begin:
                        blocked.add(contract["vehicle_id"])
                reserved = min(total, len(blocked))
                values = {"spot_master_id": spot_id, "model_id": model_id, "target_date": target,
                          "total_qty": total, "reserved_qty": reserved, "available_qty": total - reserved,
                          "calculated_at": at, "updated_at": at}
                existing = session.execute(select(inventory.c.inventory_id).where(
                    inventory.c.spot_master_id == spot_id, inventory.c.model_id == model_id,
                    inventory.c.target_date == target).with_for_update()).first()
                if existing:
                    session.execute(update(inventory).where(inventory.c.inventory_id == existing[0]).values(**values))
                else:
                    session.execute(inventory.insert().values(**values))
                written += 1
    return written


def _run_locked(db, name, callback):
    if db.engine.dialect.name != "mysql":
        return callback()
    with db.engine.connect() as connection:
        key = "nadree:job:" + name
        if connection.scalar(text("SELECT GET_LOCK(:key, 0)"), {"key": key}) != 1:
            raise RuntimeError("job is already running: " + name)
        try:
            return callback()
        finally:
            connection.execute(text("SELECT RELEASE_LOCK(:key)"), {"key": key})


def main():
    parser = argparse.ArgumentParser(description="Nadree rental maintenance jobs")
    parser.add_argument("job", choices=("maintenance", "payments", "inventory", "all"))
    parser.add_argument("--days", type=int, default=None)
    args = parser.parse_args()
    settings = Settings()
    db = Database(settings.database_url.get_secret_value())
    if db.engine is None:
        parser.error("NADREE_DATABASE_URL is required")
    fcm = FcmSender(settings)
    try:
        if args.job == "maintenance":
            print({"maintenanceReleased": _run_locked(db, "maintenance", lambda: expire_maintenance(db, settings))})
        elif args.job == "payments":
            print({"reservationsExpired": _run_locked(db, "payments", lambda: expire_unpaid_payments(db, settings, notifier=fcm))})
        elif args.job == "inventory":
            print({"inventoryRows": _run_locked(db, "inventory", lambda: rebuild_daily_inventory(db, settings, args.days))})
        else:
            print({"maintenanceReleased": _run_locked(db, "maintenance", lambda: expire_maintenance(db, settings)),
                   "reservationsExpired": _run_locked(db, "payments", lambda: expire_unpaid_payments(db, settings, notifier=fcm)),
                   "inventoryRows": _run_locked(db, "inventory", lambda: rebuild_daily_inventory(db, settings, args.days))})
    finally:
        fcm.close(wait=True)
        db.engine.dispose()


if __name__ == "__main__":
    main()
