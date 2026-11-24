"""Bali boundaries, current-only rentals, and immutable handover evidence."""
from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.booking_lifecycle import reconcile
from app.jobs import expire_maintenance
from app.rental_common import local_date
from app.rental_profile import decrypt, encrypt
from app.rental_reminders import run, still_current
from test_external_reservations import external, approve, during_period, row
from test_pending_reservation_approval import pending_bookings
from test_handover_v2 import handover, begin, submit_form, video, command, form

BASE = "/api/v1/nadree/rental"


def reconcile_at(ctx, at, **kwargs):
    with Session(ctx["engine"]) as session, session.begin():
        return reconcile(ctx["db"], ctx["settings"], session, at, spot_id="root", **kwargs)


def test_unapproved_end_is_inclusive_and_no_response_has_no_end_notification(external):
    ctx = external
    rid = ctx["request_booking"](0)["reservationId"]
    reservation = row(ctx, rid)
    with ctx["engine"].connect() as conn:
        before = conn.scalar(select(func.count()).select_from(ctx["db"].table("MSP_RENTAL_NOTIFICATION")))
    assert reconcile_at(ctx, reservation["end_datetime"]) == 0
    assert reconcile_at(ctx, reservation["end_datetime"] + timedelta(seconds=1)) == 1
    assert row(ctx, rid)["reservation_status"] == "NO_RESPONSE"
    assert reconcile_at(ctx, reservation["end_datetime"] + timedelta(days=1)) == 0
    with ctx["engine"].connect() as conn:
        assert conn.scalar(select(func.count()).select_from(ctx["db"].table("MSP_RENTAL_NOTIFICATION"))) == before


@pytest.mark.parametrize("protected", [False, True])
def test_expired_approval_requires_qr_recovery_and_preserves_other_protection(external, monkeypatch, protected):
    ctx = external
    rid = ctx["request_booking"](0)["reservationId"]
    reservation = approve(ctx, rid)
    vehicle = reservation["assigned_vehicle_id"]
    state = ctx["db"].table("MSP_VEHICLE_STATUS")
    if protected:
        with ctx["engine"].begin() as conn:
            conn.execute(state.update().where(state.c.vehicle_id == vehicle).values(
                status="MAINTENANCE", maintenance_until=local_date(SimpleNamespace(app=ctx["app"]), reservation["end_datetime"]) + timedelta(days=5)))
    at = during_period(ctx, rid, monkeypatch, day=3)
    assert reconcile_at(ctx, at) == 1
    assert row(ctx, rid)["reservation_status"] == "EXPIRED"
    rejected = ctx["client"].post("/nadreego/booking/action", headers=ctx["admin"],
        json={"bookedNo": "BO" + rid, "action": "APPROVE"})
    assert rejected.status_code == 409
    body = {"qrCode": ctx["qrs"][vehicle], "vehicleReturned": True, "reason": "Physical check"}
    path = "/nadreego/booking/BO" + rid + "/receipt-recovery"
    result = ctx["client"].post(path, headers=ctx["admin"], json=body)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["reservationStatus"] == "EXPIRED"
    assert result.json()["data"]["vehicleStatus"] == ("MAINTENANCE" if protected else "AVAILABLE")
    assert ctx["client"].post(path, headers=ctx["admin"], json=body).status_code == 200
    assert row(ctx, rid)["assigned_vehicle_id"] is None


def test_old_expiry_backfill_uses_approval_provenance(external):
    ctx = external
    unapproved, approved = [ctx["request_booking"](i)["reservationId"] for i in range(2)]
    approve(ctx, approved)
    r, h = ctx["db"].table("MSP_RESERVATION"), ctx["db"].table("MSP_RESERVATION_HISTORY")
    at = row(ctx, unapproved)["end_datetime"] + timedelta(days=1)
    with ctx["engine"].begin() as conn:
        for rid, previous in [(unapproved, "REQUESTED"), (approved, "APPROVED")]:
            conn.execute(r.update().where(r.c.reservation_id == rid).values(reservation_status="EXPIRED"))
            conn.execute(h.insert().values(reservation_id=rid, event_type="EXPIRED", previous_reservation_status=previous,
                new_reservation_status="EXPIRED", created_at=at))
    assert reconcile_at(ctx, at, backfill=True) == 1
    assert row(ctx, unapproved)["reservation_status"] == "NO_RESPONSE"
    assert row(ctx, approved)["reservation_status"] == "EXPIRED"


def test_one_day_walk_in_uses_walk_in_enum_and_one_daily_price(external):
    ctx = external
    from app.security import now
    today = local_date(SimpleNamespace(app=ctx["app"]), now())
    body = {"qrCode": ctx["qrs"]["pending-vehicle-0"], "returnDate": str(today)}
    quoted = ctx["client"].post(BASE + "/onsite/quote", headers=ctx["headers"], json=body)
    assert quoted.status_code == 200, quoted.text
    assert quoted.json()["price"]["rentalDays"] == 1
    result = ctx["client"].post(BASE + "/onsite/requests", headers=ctx["headers"], json={
        **body, "quoteToken": quoted.json()["quoteToken"], "clientRequestId": str(uuid.uuid4())})
    assert result.status_code == 200, result.text
    assert result.json()["item"]["requestType"] == "WALK_IN"


def test_untracked_rental_has_no_history_requires_real_return_and_stale_start_cannot_revive(external, monkeypatch):
    ctx = external
    from app.security import now
    today = local_date(SimpleNamespace(app=ctx["app"]), now())
    key = str(uuid.uuid4())
    body = {"vehicleNumber": "PENDING-0", "action": "START", "endDate": str(today),
        "qrCode": ctx["qrs"]["pending-vehicle-0"], "clientRequestId": key, "expectedStateVersion": 0}
    path = "/nadreego/vehicle/untracked-rent"
    started = ctx["client"].post(path, headers=ctx["admin"], json=body)
    assert started.status_code == 200, started.text
    assert ctx["client"].post(path, headers=ctx["admin"], json=body).json()["data"] == started.json()["data"]
    at = now() + timedelta(days=1)
    monkeypatch.setattr("app.vehicles.now", lambda: at)
    monkeypatch.setattr("app.rental_common.now", lambda: at)
    assert expire_maintenance(ctx["db"], ctx["settings"], at) == 0
    viewed = ctx["client"].post("/nadreego/vehicle/qr/validate", headers=ctx["admin"], json={"qrCode": body["qrCode"]})
    assert viewed.json()["data"]["vehicle"]["rentalStatus"] == "OVERDUE"
    returned = {"qrCode": body["qrCode"], "untrackedRentId": key, "vehicleReturned": True}
    assert ctx["client"].post("/nadreego/vehicle/return", headers=ctx["admin"], json=returned).status_code == 200
    assert ctx["client"].post(path, headers=ctx["admin"], json=body).json()["data"]["vehicleStatus"] == "AVAILABLE"
    newer = {**body, "clientRequestId": str(uuid.uuid4()), "expectedStateVersion": 2,
        "endDate": str(today + timedelta(days=2))}
    new_result = ctx["client"].post(path, headers=ctx["admin"], json=newer)
    assert new_result.status_code == 200, new_result.text
    old_return = ctx["client"].post("/nadreego/vehicle/return", headers=ctx["admin"], json=returned)
    assert old_return.status_code == 409 and old_return.json()["errorCode"] == "UNTRACKED_RENT_CHANGED"
    with ctx["engine"].connect() as conn:
        for name in ("MSP_RESERVATION", "MSP_RENTAL_CONTRACT", "MSP_RENTAL_CONTRACT_HISTORY", "MSP_RESERVATION_HISTORY"):
            assert conn.scalar(select(func.count()).select_from(ctx["db"].table(name))) == 0


@pytest.mark.parametrize("sns", [{"instagram": "at-rental-time"}, None])
def test_handover_key_is_independent_and_sns_and_consent_are_historical(handover, sns):
    ctx = handover
    ctx["settings"].field_encrypt_key = SecretStr("invalid-legacy-key-preserved")
    assert decrypt(ctx["settings"], encrypt(ctx["settings"], "private")) == "private"
    begin(ctx)
    if sns is not None:
        assert form(ctx, snsInfo=sns).status_code == 200
    submit_form(ctx)
    video(ctx)
    consent = command(ctx, "/signature/complete")
    assert consent.status_code == 200, consent.text
    item = consent.json()["item"]
    assert item["signatureCompletedAt"] and item["signatureActorUid"] == "pending-user-0"
    assert item["signatureHandoverId"] == ctx["hid"]
    users = ctx["db"].table("MSP_RENTAL_USER")
    with ctx["engine"].begin() as conn:
        conn.execute(users.update().where(users.c.uid_token == "pending-user-0").values(sns_info='{"instagram":"new-profile"}'))
    detail = ctx["client"].get(BASE + "/handovers/" + ctx["hid"], headers=ctx["headers"])
    assert detail.json()["item"]["form"]["snsInfo"] == sns
    assert not {n["event"] for n in ctx["fcm"].notifications} & {
        "HANDOVER_STARTED", "HANDOVER_FORM_SUBMITTED", "HANDOVER_CUSTOMER_COMPLETED"}


def test_delayed_customer_start_cannot_reopen_an_expired_handover(handover, monkeypatch):
    ctx = handover
    end = row(ctx, ctx["rid"])["end_datetime"]
    monkeypatch.setattr("app.handover.now", lambda: end + timedelta(seconds=1))
    result = ctx["client"].post(BASE + "/reservations/" + ctx["rid"] + "/handover", headers=ctx["headers"],
        json={"clientRequestId": str(uuid.uuid4())})
    assert result.status_code == 409 and result.json()["errorCode"] == "RESERVATION_NOT_APPROVED"
    h = ctx["db"].table("MSP_RENTAL_HANDOVER")
    with ctx["engine"].connect() as connection:
        assert connection.scalar(select(h.c.customer_started_at).where(h.c.handover_id == ctx["hid"])) is None


def test_morning_reminder_dedup_and_dispatch_guard(external, monkeypatch):
    ctx = external
    rid = ctx["request_booking"](0)["reservationId"]
    reservation = row(ctx, rid)
    at = reservation["start_datetime"] + timedelta(hours=9)
    admins = ctx["db"].table("MSP_ADMIN")
    with ctx["engine"].begin() as conn:
        conn.execute(admins.update().values(fcm_token="isolated-admin-device"))
    assert run(ctx["db"], ctx["settings"], ctx["fcm"], at=at - timedelta(seconds=1))["reminders"] == 0
    assert run(ctx["db"], ctx["settings"], ctx["fcm"], at=at)["reminders"] == 1
    assert run(ctx["db"], ctx["settings"], ctx["fcm"], at=at)["reminders"] == 0
    push = next(n for n in ctx["fcm"].notifications if n["event"] == "RESERVATION_START_UNAPPROVED")
    with ctx["engine"].begin() as conn:
        assert still_current(ctx["db"], conn, push["reminderGuard"], at)
        r = ctx["db"].table("MSP_RESERVATION")
        conn.execute(r.update().where(r.c.reservation_id == rid).values(start_datetime=reservation["start_datetime"] + timedelta(days=1)))
        assert not still_current(ctx["db"], conn, push["reminderGuard"], at)
        conn.execute(r.update().where(r.c.reservation_id == rid).values(reservation_status="REJECTED", start_datetime=reservation["start_datetime"]))
        assert not still_current(ctx["db"], conn, push["reminderGuard"], at)


def test_direct_vehicle_counts_and_effectively_inactive_descendants(external):
    ctx = external
    db = ctx["db"]
    master, history, vehicle = [db.table(n) for n in ("MSP_SPOT_MASTER", "MSP_VEHICLE_SPOT_HISTORY", "MSP_VEHICLE")]
    with ctx["engine"].begin() as conn:
        child = dict(conn.execute(select(master).where(master.c.spot_master_id == "child")).mappings().one())
        conn.execute(master.insert().values(**{**child, "spot_master_id": "grandchild", "spot_id": "grandchild-spot",
            "unit_code": child["unit_code"] + "-NEST"}))
        conn.execute(master.update().where(master.c.spot_master_id == "child").values(is_active=0))
        conn.execute(history.update().where(history.c.vehicle_id == "pending-vehicle-0").values(spot_master_id="child"))
        conn.execute(vehicle.update().where(vehicle.c.vehicle_id == "pending-vehicle-0").values(is_active=0))
    result = ctx["client"].get("/api/v1/organizations/spots/hierarchy", headers=ctx["admin"],
        params={"includeSelf": True})
    assert result.status_code == 200, result.text
    items = {r["spot_master_id"]: r for r in result.json()["items"]}
    assert items["root"]["directVehicleCount"] == 2
    assert items["child"]["directVehicleCount"] == 1  # Inactive vehicles are included.
    assert items["grandchild"]["directVehicleCount"] == 0
    assert items["child"]["is_active"] is False and items["grandchild"]["is_active"] is False
    inactive = ctx["client"].get("/api/v1/organizations/spots/hierarchy?is_active=0", headers=ctx["admin"])
    assert {r["spot_master_id"] for r in inactive.json()["items"]} == {"child", "grandchild"}


def test_recent_three_include_canceled_former_assignments_and_hide_foreign_vehicle(external, signin):
    ctx = external
    ids = [ctx["request_booking"](i, offset=i * 4)["reservationId"] for i in range(4)]
    r, h = ctx["db"].table("MSP_RESERVATION"), ctx["db"].table("MSP_RESERVATION_HISTORY")
    with ctx["engine"].begin() as conn:
        conn.execute(r.update().where(r.c.reservation_id.in_(ids)).values(assigned_vehicle_id="pending-vehicle-0"))
        conn.execute(r.update().where(r.c.reservation_id == ids[3]).values(reservation_status="CANCELED", assigned_vehicle_id=None))
        conn.execute(h.insert().values(reservation_id=ids[3], event_type="CANCELLED",
            previous_vehicle_id="pending-vehicle-0", new_vehicle_id=None, created_at=row(ctx, ids[3])["created_at"]))
    path = "/nadreego/vehicle/pending-vehicle-0/rental-history"
    result = ctx["client"].get(path, headers=ctx["admin"])
    assert result.status_code == 200, result.text
    assert [i["reservationId"] for i in result.json()["items"]] == ids[:0:-1]
    assert result.json()["items"][0]["vehicleAssociation"] == "PREVIOUS_ASSIGNMENT"
    assert result.json()["items"][0]["reservationStatus"] == "CANCELED"
    assert ctx["client"].get(path, headers=signin("outsider")).status_code == 404


def test_actual_rental_is_overdue_only_after_end_day_and_reminders_stop_after_return(external, monkeypatch):
    from test_customer_receipt import prepare, receive
    ctx = external
    rid = ctx["request_booking"](0)["reservationId"]
    approve(ctx, rid)
    during_period(ctx, rid, monkeypatch)
    assert prepare(ctx, rid).status_code == 200
    assert receive(ctx, rid).status_code == 200
    r = row(ctx, rid)
    c = ctx["db"].table("MSP_RENTAL_CONTRACT")
    end_day_nine = r["end_datetime"].replace(hour=1, minute=0, second=0)  # UTC01:00 == Bali09:00.
    assert run(ctx["db"], ctx["settings"], ctx["fcm"], at=end_day_nine)["reminders"] == 1
    with ctx["engine"].connect() as conn:
        assert conn.scalar(select(c.c.contract_status)) == "ON_RENT"
    overdue_at = r["end_datetime"] + timedelta(seconds=1)
    assert reconcile_at(ctx, overdue_at) == 1
    assert row(ctx, rid)["reservation_status"] == "HANDED_OVER"
    with ctx["engine"].begin() as conn:
        assert conn.scalar(select(c.c.contract_status)) == "OVERDUE"
        conn.execute(c.update().values(contract_status="RETURNED", actual_end_time=overdue_at))
    assert run(ctx["db"], ctx["settings"], ctx["fcm"], at=end_day_nine + timedelta(days=1))["reminders"] == 0


def test_price_edit_does_not_invalidate_previously_approved_quote(handover):
    ctx = handover
    detail = ctx["client"].get(BASE + "/reservations/" + ctx["rid"], headers=ctx["headers"])
    assert detail.json()["item"]["customerReceiptRequired"] is False
    r = row(ctx, ctx["rid"])
    vehicle = r["assigned_vehicle_id"]
    result = ctx["client"].post("/nadreego/vehicle/priceChange", headers=ctx["admin"], json={
        "vehicleNumber": "PENDING-" + vehicle[-1], "priceType": "PREMIUM", "priceInfo": 99})
    assert result.status_code == 200, result.text
    assert row(ctx, ctx["rid"])["required_criteria_json"]["dailyPrice"] == 10
    begin(ctx)
    submit_form(ctx)
    video(ctx)
    from test_handover_v2 import claim, start_rent
    claim(ctx)
    assert command(ctx, "/signature/complete").status_code == 200
    assert command(ctx, "/review", {"action": "CONFIRM"}, admin=True).status_code == 200
    started = start_rent(ctx)
    assert started.status_code == 200 and started.json()["data"]["finalPrice"] == 25
