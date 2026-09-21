from datetime import date, datetime, timedelta

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, select

from app.jobs import expire_maintenance, expire_unpaid_payments, rebuild_daily_inventory
from app.rental_schema import metadata as rental_metadata
from app.security import now


class RecordingNotifier:
    def __init__(self):
        self.notifications = []

    def dispatch(self, db, notifications):
        self.notifications.extend(notifications)


def test_jobs_release_maintenance_and_rebuild_inventory(setup):
    rental_metadata.create_all(setup["engine"])
    db, engine, settings = setup["db"], setup["engine"], setup["settings"]
    extra_metadata = MetaData()
    Table("MSP_VEHICLE", extra_metadata, Column("vehicle_id", String(36), primary_key=True), Column("is_active", Integer))
    Table("MSP_VEHICLE_SPOT_HISTORY", extra_metadata,
          Column("history_id", Integer, primary_key=True, autoincrement=True), Column("vehicle_id", String(36)),
          Column("spot_master_id", String(36)), Column("assigned_at", DateTime), Column("released_at", DateTime))
    extra_metadata.create_all(engine)
    extra = {name: db.table(name) for name in (
        "MSP_VEHICLE", "MSP_VEHICLE_SPOT_HISTORY", "MSP_RENTAL_VEHICLE", "MSP_VEHICLE_MODEL",
        "MSP_VEHICLE_STATUS", "MSP_MODEL_DAILY_INVENTORY")}
    at = datetime(2026, 9, 21, 1, 0)
    with engine.begin() as conn:
        conn.execute(extra["MSP_VEHICLE"].insert().values(vehicle_id="job-v1", is_active=1))
        conn.execute(extra["MSP_VEHICLE_SPOT_HISTORY"].insert().values(
            vehicle_id="job-v1", spot_master_id="root", assigned_at=now()))
        conn.execute(extra["MSP_VEHICLE_MODEL"].insert().values(
            model_id="job-m1", brand="Nadree", model_name="Job scooter", vehicle_type="SCOOTER",
            is_active=1, created_at=now(), updated_at=now()))
        conn.execute(extra["MSP_RENTAL_VEHICLE"].insert().values(
            vehicle_id="job-v1", model_id="job-m1", rental_enabled=1, price_type="BASIC",
            created_at=now(), updated_at=now()))
        conn.execute(extra["MSP_VEHICLE_STATUS"].insert().values(
            vehicle_id="job-v1", status="MAINTENANCE", maintenance_until=date(2026, 9, 19),
            status_changed_at=now(), created_at=now(), updated_at=now()))
    assert expire_maintenance(db, settings, at=at) == 1
    written = rebuild_daily_inventory(db, settings, days=3, at=at)
    assert written == 3
    with engine.connect() as conn:
        rows = conn.execute(select(extra["MSP_MODEL_DAILY_INVENTORY"]).order_by(
            extra["MSP_MODEL_DAILY_INVENTORY"].c.target_date)).mappings().all()
    assert [row["available_qty"] for row in rows] == [1, 1, 1]


def test_unpaid_payment_expiry_releases_approved_reservation(setup):
    rental_metadata.create_all(setup["engine"])
    db, engine, settings = setup["db"], setup["engine"], setup["settings"]
    reservation = db.table("MSP_RESERVATION")
    payment = db.table("MSP_RENTAL_PAYMENT")
    old = datetime(2026, 9, 17)
    with engine.begin() as conn:
        conn.execute(reservation.insert().values(
            reservation_id="job-r1", uid_token="job-u1", spot_master_id="root", model_id="job-m1",
            assigned_vehicle_id=None, vehicle_assignment_status="PROVISIONAL", start_datetime=old,
            end_datetime=old + timedelta(days=1), reservation_status="APPROVED",
            created_at=old, updated_at=old))
        conn.execute(payment.insert().values(
            reservation_id="job-r1", payment_provider="PAYPAL", payment_environment="SANDBOX",
            payment_status="CREATED", total_price=100, currency="USD", refunded_amount=0,
            refund_status="NONE", created_at=old, updated_at=old))
    assert expire_unpaid_payments(db, settings, at=datetime(2026, 9, 21)) == 1
    with engine.connect() as conn:
        assert conn.scalar(select(reservation.c.reservation_status).where(reservation.c.reservation_id == "job-r1")) == "EXPIRED"
        assert conn.scalar(select(payment.c.payment_status).where(payment.c.reservation_id == "job-r1")) == "CANCELED"


def test_payment_deadline_reminders_and_expiry_notify_once(setup):
    rental_metadata.create_all(setup["engine"])
    db, engine, settings = setup["db"], setup["engine"], setup["settings"]
    user, reservation, history = (db.table(name) for name in
                                  ("MSP_RENTAL_USER", "MSP_RESERVATION", "MSP_RESERVATION_HISTORY"))
    approved_at = datetime(2026, 9, 17)
    with engine.begin() as conn:
        conn.execute(user.insert().values(uid_token="deadline-user", fcm_token="deadline-device",
                                          fcm_token_updated_at=approved_at))
        conn.execute(reservation.insert().values(
            reservation_id="deadline-r1", uid_token="deadline-user", spot_master_id="root", model_id="job-m1",
            assigned_vehicle_id="deadline-v1", vehicle_assignment_status="PROVISIONAL",
            start_datetime=approved_at, end_datetime=approved_at + timedelta(days=3),
            reservation_status="APPROVED", created_at=approved_at, updated_at=approved_at))
        conn.execute(history.insert().values(
            reservation_id="deadline-r1", event_type="APPROVED",
            previous_reservation_status="REQUESTED", new_reservation_status="APPROVED",
            previous_vehicle_id=None, new_vehicle_id="deadline-v1",
            previous_assignment_status="SOFT_HOLD", new_assignment_status="PROVISIONAL",
            changed_by="admin", created_at=approved_at))
    notifier = RecordingNotifier()
    assert expire_unpaid_payments(db, settings, at=datetime(2026, 9, 18), notifier=notifier) == 0
    assert [item["event"] for item in notifier.notifications] == ["PAYMENT_DEADLINE_2_DAY"]
    assert expire_unpaid_payments(db, settings, at=datetime(2026, 9, 18), notifier=notifier) == 0
    assert len(notifier.notifications) == 1
    assert expire_unpaid_payments(db, settings, at=datetime(2026, 9, 19), notifier=notifier) == 0
    assert [item["event"] for item in notifier.notifications] == ["PAYMENT_DEADLINE_2_DAY", "PAYMENT_DEADLINE_1_DAY"]
    assert expire_unpaid_payments(db, settings, at=datetime(2026, 9, 20), notifier=notifier) == 1
    assert notifier.notifications[-1]["event"] == "RESERVATION_PAYMENT_EXPIRED"
    with engine.connect() as conn:
        assert conn.scalar(select(reservation.c.reservation_status).where(
            reservation.c.reservation_id == "deadline-r1")) == "EXPIRED"
    assert expire_unpaid_payments(db, settings, at=datetime(2026, 9, 21), notifier=notifier) == 0
    assert len(notifier.notifications) == 3
