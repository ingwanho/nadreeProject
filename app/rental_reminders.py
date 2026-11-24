"""Once-per-day rental reminders, using the existing SQL event history."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.booking_lifecycle import reconcile
from app.fcm import _manager_recipients, _queue
from app.notifications import record_notification
from app.security import now


def local_day(settings, value):
    return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.business_timezone)).date()


def queue(db, settings, session, row, event, at, *, rental=False, admins=False, customer=False):
    day = local_day(settings, at).isoformat()
    ident = row["rental_contract_id"] if rental else row["reservation_id"]
    history = db.table("MSP_RENTAL_CONTRACT_HISTORY" if rental else "MSP_RESERVATION_HISTORY")
    key = history.c.rental_contract_id if rental else history.c.reservation_id
    if session.scalar(select(history.c.history_id).where(key == ident, history.c.event_type == event,
            history.c.reason == "BALI_09:" + day)):
        return 0
    status = row["contract_status"] if rental else row["reservation_status"]
    values = {"rental_contract_id" if rental else "reservation_id": ident, "event_type": event,
        "previous_contract_status" if rental else "previous_reservation_status": status,
        "new_contract_status" if rental else "new_reservation_status": status, "changed_by": None,
        "reason": "BALI_09:" + day, "created_at": at}
    session.execute(history.insert().values(**values))
    booked_no = "BO" + row["reservation_id"] if row.get("reservation_id") else "RT" + ident
    data = {"type": event, "bookedNo": booked_no, "eventId": event + ":" + ident + ":" + day}
    if row.get("reservation_id"):
        data["reservationId"] = row["reservation_id"]
    if rental:
        data["rentalContractId"] = ident
    shop = row["pickup_spot_master_id"] if rental else row["spot_master_id"]
    messages = {"RESERVATION_START_UNAPPROVED": "A reservation starting today is still awaiting your decision.",
        "RESERVATION_PICKUP_DUE": "Your rental starts today. Please arrange vehicle pickup with the shop.",
        "RENTAL_RETURN_DUE": "Your vehicle rental is due for return today.",
        "RENTAL_OVERDUE_STARTED": "A vehicle rental is overdue. Please check its return status."}
    before = len(session.info.get("fcm_notifications", []))
    if admins:
        _queue(session, table="MSP_ADMIN", key_column="admin_id", recipients=_manager_recipients(db, session, shop),
            event=event, title="Rental reminder", body=messages[event], data=data)
        record_notification(db, session, shop, event, "RENTAL" if rental else "RESERVATION", ident, data["eventId"])
    if customer and row.get("uid_token"):
        users = db.table("MSP_RENTAL_USER")
        user = session.execute(select(users).where(users.c.uid_token == row["uid_token"])).mappings().first()
        if user:
            _queue(session, table="MSP_RENTAL_USER", key_column="uid_token", recipients=[{
                "id": user["uid_token"], "token": user.get("fcm_token"), "updated_at": user.get("fcm_token_updated_at")}],
                event=event, title="Rental reminder", body=messages[event], data=data)
    guard = {"id": ident, "rental": rental, "day": day, "timezone": settings.business_timezone, "event": event}
    for notification in session.info.get("fcm_notifications", [])[before:]:
        notification["reminderGuard"] = guard
    return 1


def run(db, settings, notifier, *, at=None, backfill=False):
    at = at or now()
    today = local_day(settings, at)
    nine = datetime.combine(today, time(9), ZoneInfo(settings.business_timezone)).astimezone(timezone.utc).replace(tzinfo=None)
    changed, reminders = 0, 0
    with Session(db.engine) as session, session.begin():
        master, r, c = (db.table(n) for n in ("MSP_SPOT_MASTER", "MSP_RESERVATION", "MSP_RENTAL_CONTRACT"))
        shops = list(session.scalars(select(master.c.spot_master_id).order_by(master.c.spot_master_id).with_for_update()))
        for shop in shops:
            changed += reconcile(db, settings, session, at, spot_id=shop, backfill=backfill)
            if at < nine or backfill:
                continue
            bookings = session.execute(select(r).where(r.c.spot_master_id == shop,
                r.c.reservation_status.in_(("REQUESTED", "APPROVED", "HANDOVER_PENDING")))).mappings()
            for row in bookings:
                if not row["start_datetime"] or local_day(settings, row["start_datetime"]) != today or row["created_at"] > nine:
                    continue
                requested = row["reservation_status"] == "REQUESTED"
                if not requested:
                    h = db.table("MSP_RESERVATION_HISTORY")
                    approval = session.scalar(select(h.c.created_at).where(h.c.reservation_id == row["reservation_id"],
                        h.c.event_type == "APPROVED").order_by(h.c.created_at))
                    if not approval or approval > nine:
                        continue
                reminders += queue(db, settings, session, row,
                    "RESERVATION_START_UNAPPROVED" if requested else "RESERVATION_PICKUP_DUE", at,
                    admins=requested, customer=not requested)
            contracts = session.execute(select(c).where(c.c.pickup_spot_master_id == shop,
                c.c.contract_status.in_(("ON_RENT", "OVERDUE")), c.c.actual_end_time.is_(None))).mappings()
            for row in contracts:
                if not row["planned_end_date"] or not row["actual_start_time"] or row["actual_start_time"] > nine:
                    continue
                if row["planned_end_date"] == today:
                    reminders += queue(db, settings, session, row, "RENTAL_RETURN_DUE", at, rental=True, admins=True, customer=True)
                elif row["planned_end_date"] + timedelta(days=1) == today:
                    reminders += queue(db, settings, session, row, "RENTAL_OVERDUE_STARTED", at, rental=True, admins=True)
            state = db.table("MSP_VEHICLE_STATUS")
            membership = db.table("MSP_VEHICLE_SPOT_HISTORY")
            manual = session.execute(select(state).join(membership, membership.c.vehicle_id == state.c.vehicle_id)
                .where(membership.c.spot_master_id == shop, membership.c.released_at.is_(None),
                       state.c.status == "UNTRACKED_RENT", state.c.status_changed_at <= nine)).mappings()
            for row in manual:
                until = row["untracked_rent_until"]
                if until not in (today, today - timedelta(days=1)):
                    continue
                event = "UNTRACKED_RETURN_DUE" if until == today else "UNTRACKED_OVERDUE_STARTED"
                event_id = event + ":" + (row.get("operation_id") or row["vehicle_id"]) + ":" + today.isoformat()
                inbox = db.table("MSP_RENTAL_NOTIFICATION")
                if session.scalar(select(inbox.c.notification_id).where(inbox.c.event_key == event_id)):
                    continue
                record_notification(db, session, shop, event, "VEHICLE", row["vehicle_id"], event_id)
                before = len(session.info.get("fcm_notifications", []))
                _queue(session, table="MSP_ADMIN", key_column="admin_id", recipients=_manager_recipients(db, session, shop),
                    event=event, title="Rental reminder", body="Please check the return of the customer-free rental vehicle.",
                    data={"type": event, "vehicleId": row["vehicle_id"], "eventId": event_id})
                for notification in session.info.get("fcm_notifications", [])[before:]:
                    notification["reminderGuard"] = {"id": row["vehicle_id"], "untracked": True,
                        "operationId": row.get("operation_id"), "day": today.isoformat(),
                        "timezone": settings.business_timezone, "event": event}
                reminders += 1
        notifications = session.info.pop("fcm_notifications", [])
    notifier.dispatch(db, notifications)
    return {"transitions": changed, "reminders": reminders}


def still_current(db, connection, guard, at):
    zone = ZoneInfo(guard["timezone"])
    today = at.replace(tzinfo=timezone.utc).astimezone(zone).date()
    if today.isoformat() != guard["day"]:
        return False
    if guard.get("untracked"):
        state = db.table("MSP_VEHICLE_STATUS")
        row = connection.execute(select(state).where(state.c.vehicle_id == guard["id"])).mappings().first()
        return bool(row and row["status"] == "UNTRACKED_RENT" and row.get("operation_id") == guard["operationId"]
            and row["untracked_rent_until"] == today - timedelta(days=guard["event"] == "UNTRACKED_OVERDUE_STARTED"))
    table = db.table("MSP_RENTAL_CONTRACT" if guard["rental"] else "MSP_RESERVATION")
    key = table.c.rental_contract_id if guard["rental"] else table.c.reservation_id
    row = connection.execute(select(table).where(key == guard["id"])).mappings().first()
    if not row:
        return False
    if guard["rental"]:
        return bool(row["actual_end_time"] is None and row["contract_status"] in ("ON_RENT", "OVERDUE") and
            row["planned_end_date"] == today - timedelta(days=guard["event"] == "RENTAL_OVERDUE_STARTED"))
    return bool(row["start_datetime"] and row["start_datetime"].replace(tzinfo=timezone.utc).astimezone(zone).date() == today
        and row["reservation_status"] in (("REQUESTED",) if guard["event"] == "RESERVATION_START_UNAPPROVED" else ("APPROVED", "HANDOVER_PENDING")))
