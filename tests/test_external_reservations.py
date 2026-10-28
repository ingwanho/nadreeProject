"""Real API/solver/SQL regression in disposable SQLite; no external services."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.config import Settings
from app.jobs import expire_unpaid_payments
from app.reservation_payments import EXTERNAL, PAYPAL, payment_method
from app.security import now, sign_user_access
from test_nadri_flow import RecordingFcm
from test_pending_reservation_approval import pending_bookings
from test_payment_safety import (payments, insert_payment, payment_rows, order, capture,
                                 test_settlement_only_recovers_completed_capture_once_without_push_or_provider_writes as _assert_settlement_recovery)


@pytest.fixture
def external(setup, pending_bookings, signin, monkeypatch):
    tables, request_booking = pending_bookings
    settings = setup["settings"]
    settings.reservation_payment_method = EXTERNAL
    settings.paypal_checkout_enabled = False
    settings.qr_hash_key = SecretStr("isolated-external-qr-key-at-least-32-bytes")
    fcm = RecordingFcm()
    setup["app"].state.fcm = fcm

    def forbidden(*args, **kwargs):
        pytest.fail("External reservation must not call PayPal")

    for name in ("verify_merchant", "get", "create_order", "capture_order", "refund", "onboarding_url", "seller_by_tracking"):
        monkeypatch.setattr(setup["app"].state.paypal, name, forbidden)
    from app.rental_common import qr_digest
    qr_values = {}
    with setup["engine"].begin() as conn:
        spot = setup["db"].table("MSP_SPOT_RENT")
        conn.execute(spot.update().values(paypal_merchant_id=None, paypal_environment=None))
        users = tables["MSP_RENTAL_USER"]
        conn.execute(users.update().where(users.c.uid_token == "pending-user-0").values(fcm_token="isolated-device"))
        for i in range(3):
            raw = "isolated-external-qr-" + str(i)
            ident = "pending-vehicle-" + str(i)
            qr_values[ident] = raw
            conn.execute(tables["MSP_VEHICLE_QR"].insert().values(qr_id="qr-" + str(i), vehicle_id=ident,
                qr_code_hash=qr_digest(SimpleNamespace(app=setup["app"]), raw), qr_status="ACTIVE", issued_at=now()))
    return {**setup, "tables": tables, "request_booking": request_booking, "admin": signin(),
            "headers": {"Authorization": "Bearer " + sign_user_access(settings, "pending-user-0")},
            "fcm": fcm, "qrs": qr_values}


def row(ctx, ident):
    t = ctx["tables"]["MSP_RESERVATION"]
    with ctx["engine"].connect() as conn:
        return dict(conn.execute(select(t).where(t.c.reservation_id == ident)).mappings().one())


def approve(ctx, ident):
    response = ctx["client"].post("/nadreego/booking/action", headers=ctx["admin"],
        json={"bookedNo": "BO" + ident, "action": "APPROVE"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["paymentMethod"] == EXTERNAL
    return row(ctx, ident)


def during_period(ctx, ident, monkeypatch, *, day=0):
    at = row(ctx, ident)["start_datetime"] + timedelta(hours=12, days=day)
    for module in ("rentals", "customer_rentals", "rental_common", "availability"):
        monkeypatch.setattr("app." + module + ".now", lambda: at)
    return at


def handover(ctx, ident, headers=None):
    r = row(ctx, ident)
    return ctx["client"].post("/nadreego/rent/approve", headers=headers or ctx["admin"],
        json={"bookedNo": "BO" + ident, "qrCode": ctx["qrs"][r["assigned_vehicle_id"]]})


def operation(ctx, ident):
    response = ctx["client"].post("/nadreego/booking/select", headers=ctx["admin"],
        json={"bookedNo": "BO" + ident, "page": 1, "pageSize": 10})
    assert response.status_code == 200, response.text
    return response.json()["items"][0]


def calendar_event(ctx, ident):
    r = row(ctx, ident)
    from zoneinfo import ZoneInfo
    from datetime import timezone
    start = r["start_datetime"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo(ctx["settings"].business_timezone)).date()
    response = ctx["client"].post("/nadreego/main/calendar", headers=ctx["admin"],
        json={"startDate": str(start), "endDate": str(start + timedelta(days=5)), "page": 1, "pageSize": 10})
    assert response.status_code == 200, response.text
    return next(e for v in response.json()["items"] for e in v["events"] if e["reservationId"] == ident)


def assert_no_payments(ctx):
    with ctx["engine"].connect() as conn:
        assert conn.scalar(select(func.count()).select_from(ctx["tables"]["MSP_RENTAL_PAYMENT"])) == 0


def test_safe_defaults_and_legacy_classification():
    settings = Settings(_env_file=None)
    assert settings.reservation_payment_method == EXTERNAL
    assert settings.paypal_checkout_enabled is False
    assert payment_method({"required_criteria_json": {}}) == PAYPAL
    assert payment_method({"required_criteria_json": {"paymentMethod": EXTERNAL}}) == EXTERNAL


@pytest.mark.parametrize("sensor", [False, True])
@pytest.mark.parametrize("admin", ["primary", "general"])
@pytest.mark.parametrize("chat_enabled", [False, True])
def test_request_approval_qr_handover_return_without_paypal(external, signin, monkeypatch, sensor, admin, chat_enabled):
    ctx = external
    ctx["admin"] = signin(admin)
    chat_events = []
    if chat_enabled:
        class ChatBridge:
            def sync_booking(self, db, ident):
                chat_events.append(("sync", ident))

            def block_booking(self, ident):
                chat_events.append(("block", ident))
        ctx["settings"].fcm_chat_enabled = True
        ctx["app"].state.chat = ChatBridge()
    request_data = ctx["request_booking"](0)
    ident = request_data["reservationId"]
    assert request_data["paymentMethod"] == EXTERNAL
    assert request_data["paymentStatus"] is None
    assert request_data["canPay"] is False and request_data["canCapture"] is False
    approved = approve(ctx, ident)
    assert approved["required_criteria_json"]["paymentMethod"] == EXTERNAL
    push = next(n for n in ctx["fcm"].notifications if n["event"] == "RESERVATION_APPROVED")
    assert "현장 또는 외부" in push["body"] and "3일" not in push["body"] and "10%" not in push["body"]
    assert push["data"]["paymentMethod"] == EXTERNAL
    assert operation(ctx, ident)["canHandOver"] is False
    assert handover(ctx, ident).json()["errorCode"] == "OUTSIDE_RESERVATION_PERIOD"
    if sensor:
        with ctx["engine"].begin() as conn:
            conn.execute(ctx["tables"]["MSP_SENSOR"].insert().values(
                sensor_id="isolated-sensor", vehicle_id=approved["assigned_vehicle_id"], is_active=1))
    during_period(ctx, ident, monkeypatch)
    for data in (operation(ctx, ident), calendar_event(ctx, ident)):
        assert data["paymentMethod"] == EXTERNAL and data["onlinePaymentEnabled"] is False
        assert data["canHandOver"] is True and "RENT_APPROVE" in data["availableActions"]
    for path in ("/ongoing", "/reservations/" + ident):
        response = ctx["client"].get("/api/v1/nadree/rental" + path, headers=ctx["headers"])
        assert response.status_code == 200, response.text
        item = response.json().get("item") or response.json()["items"][0]
        assert item["paymentMethod"] == EXTERNAL and item["paymentAvailability"] == "EXTERNAL_PAYMENT"
        assert item["payment"] is None and item["paymentStatus"] is None and item["paymentDeadline"] is None
        assert item["canPay"] is False and item["price"]["finalTotal"] == 30
    response = handover(ctx, ident)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["contractStatus"] == "ON_RENT"
    with ctx["engine"].connect() as conn:
        contract = conn.execute(select(ctx["tables"]["MSP_RENTAL_CONTRACT"])).mappings().one()
        assert bool(contract["sensor_id"]) == sensor
    returned = ctx["client"].post("/nadreego/vehicle/return", headers=ctx["admin"],
        json={"qrCode": ctx["qrs"][approved["assigned_vehicle_id"]]})
    assert returned.status_code == 200, returned.text
    completed = ctx["client"].get("/api/v1/nadree/rental/completed", headers=ctx["headers"]).json()["items"][0]
    assert completed["rentalStatus"] == "RETURNED" and completed["paymentMethod"] == EXTERNAL
    assert completed["payment"] is None
    if chat_enabled:
        assert ("block", ident) in chat_events and chat_events[-1] == ("sync", ident)
    assert_no_payments(ctx)


def test_external_snapshot_survives_paypal_reenable(external):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    ctx["settings"].reservation_payment_method = PAYPAL
    ctx["settings"].paypal_checkout_enabled = True
    approve(ctx, ident)  # Still no seller verification, despite the changed global policy.
    response = ctx["client"].post("/api/v1/nadree/rental/payment/order", headers=ctx["headers"], json={"reservationId": ident})
    assert response.status_code == 409 and response.json()["errorCode"] == "ONLINE_PAYMENT_NOT_REQUIRED"
    assert_no_payments(ctx)


def test_multiple_pending_external_bookings_preserve_inventory(external):
    ctx = external
    ids = [ctx["request_booking"](i)["reservationId"] for i in range(3)]
    before = [row(ctx, ident) for ident in ids]
    approve(ctx, ids[1])
    assert row(ctx, ids[0]) == before[0] and row(ctx, ids[2]) == before[2]
    assert ctx["request_booking"](3, expected=409)["errorCode"] == "RENTAL_UNAVAILABLE"


@pytest.mark.parametrize("after_days", [4, 20])
def test_external_booking_has_no_payment_expiry_or_reminders(external, after_days):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    approved = approve(ctx, ident)
    before_notifications = len(ctx["fcm"].notifications)
    assert expire_unpaid_payments(ctx["db"], ctx["settings"], at=now() + timedelta(days=after_days),
                                 notifier=ctx["fcm"], paypal=ctx["app"].state.paypal) == 0
    assert row(ctx, ident) == approved
    assert len(ctx["fcm"].notifications) == before_notifications
    assert_no_payments(ctx)


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("rental_day", [False, True])
def test_external_customer_cancel_never_creates_refund(external, monkeypatch, approved, rental_day):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    if approved:
        approve(ctx, ident)
    if rental_day:
        during_period(ctx, ident, monkeypatch)
    response = ctx["client"].post("/api/v1/nadree/rental/request/cancel", headers=ctx["headers"], json={"reservationId": ident})
    assert response.status_code == 200, response.text
    assert response.json()["refundStatus"] == "NOT_REQUIRED"
    assert response.json()["refundRequestedAmount"] == 0
    assert response.json()["refundReason"] == "EXTERNAL_PAYMENT_MANAGED_BY_SHOP"
    assert row(ctx, ident)["vehicle_assignment_status"] == "RELEASED"
    assert_no_payments(ctx)


def test_external_admin_cancel_has_no_fictitious_refund_percentage(external, monkeypatch):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    during_period(ctx, ident, monkeypatch)
    response = ctx["client"].post("/nadreego/booking/action", headers=ctx["admin"],
        json={"bookedNo": "BO" + ident, "action": "CANCEL"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["refundStatus"] == "NOT_REQUIRED"
    assert row(ctx, ident)["required_criteria_json"]["cancellation"]["refundPercentage"] is None
    assert_no_payments(ctx)


@pytest.mark.parametrize("state", ["CREATED", "PENDING", "PAID"])
def test_disabled_checkout_blocks_legacy_commands_but_retains_read_only_status(payments, monkeypatch, state):
    ctx = payments
    ctx["settings"].paypal_checkout_enabled = False
    ident = insert_payment(ctx, payment_status=state, paypal_order_id="safe-order",
        paypal_capture_id="capture" if state == "PAID" else None, paid_at=now() if state == "PAID" else None)
    before = dict(payment_rows(ctx)[0])
    def forbidden(*args, **kwargs):
        pytest.fail("Disabled checkout/status must not contact PayPal")
    monkeypatch.setattr(ctx["pg"], "get", forbidden)
    for response in (order(ctx), capture(ctx, ident)):
        assert response.status_code == 409 and response.json()["errorCode"] == "ONLINE_PAYMENT_DISABLED"
    data = ctx["client"].get("/api/v1/nadree/rental/payment/" + str(ident), headers=ctx["headers"]).json()
    assert data["paymentStatus"] == state and data["paymentMethod"] == PAYPAL
    assert data["onlinePaymentEnabled"] is False and data["canPay"] is False and data["canCapture"] is False
    assert data["approvalUrl"] is None and data["providerStateChecked"] is False
    assert data["nextAction"] == ("DONE" if state == "PAID" else "NONE")
    assert dict(payment_rows(ctx)[0]) == before
    assert not ctx["pg"].orders and not ctx["pg"].captures


def test_pending_capture_remains_wait_for_existing_settlement_when_checkout_disabled(payments):
    payments["settings"].paypal_checkout_enabled = False
    ident = insert_payment(payments, payment_status="PENDING", paypal_capture_id="capture")
    data = payments["client"].get("/api/v1/nadree/rental/payment/" + str(ident), headers=payments["headers"]).json()
    assert data["nextAction"] == "WAIT" and data["canCapture"] is False


def test_legacy_refund_still_runs_when_checkout_disabled(payments):
    payments["settings"].paypal_checkout_enabled = False
    insert_payment(payments, payment_status="PAID", paid_at=now(), paypal_capture_id="capture")
    response = payments["client"].post("/api/v1/nadree/rental/request/cancel", headers=payments["headers"],
        json={"reservationId": "safe-booking"})
    assert response.status_code == 200, response.text
    assert len(payments["pg"].refunds) == 1
    assert response.json()["refundRequestedAmount"] == 90


def test_legacy_settlement_still_runs_when_checkout_disabled(payments, monkeypatch):
    payments["settings"].paypal_checkout_enabled = False
    _assert_settlement_recovery(payments, monkeypatch)


@pytest.mark.parametrize("paid,refund,extra,allowed", [(False, "NONE", False, False), (True, "NONE", False, True),
    (True, "REQUESTED", False, False), (True, "PENDING", False, False), (True, "NONE", True, False)])
def test_legacy_online_handover_actions_match_execution(external, monkeypatch, paid, refund, extra, allowed):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    r, p = ctx["tables"]["MSP_RESERVATION"], ctx["tables"]["MSP_RENTAL_PAYMENT"]
    criteria = row(ctx, ident)["required_criteria_json"]
    criteria.pop("paymentMethod")  # Explicit legacy fixture: no mode metadata.
    with ctx["engine"].begin() as conn:
        conn.execute(r.update().where(r.c.reservation_id == ident).values(required_criteria_json=criteria))
        if paid:
            conn.execute(p.insert().values(reservation_id=ident, payment_environment="SANDBOX", payment_status="PAID",
                paypal_merchant_id="SELLER1234567", total_price=30, currency="USD", paypal_capture_id="capture",
                paid_at=now(), refund_status=refund))
        if extra:
            conn.execute(p.insert().values(reservation_id=ident, payment_environment="SANDBOX", payment_status="PENDING",
                paypal_merchant_id="SELLER1234567", total_price=30, currency="USD"))
    during_period(ctx, ident, monkeypatch)
    for data in (operation(ctx, ident), calendar_event(ctx, ident)):
        assert data["paymentMethod"] == PAYPAL
        assert data["canHandOver"] == allowed
        assert ("RENT_APPROVE" in data["availableActions"]) == allowed
    response = handover(ctx, ident)
    assert (response.status_code == 200) == allowed, response.text


@pytest.mark.parametrize("operation_name", ["APPROVE", "HANDOVER", "CANCEL"])
def test_external_reservation_with_unexpected_financial_record_fails_closed(external, monkeypatch, operation_name):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    if operation_name != "APPROVE":
        approve(ctx, ident)
        during_period(ctx, ident, monkeypatch)
    with ctx["engine"].begin() as conn:
        conn.execute(ctx["tables"]["MSP_RENTAL_PAYMENT"].insert().values(
            reservation_id=ident, payment_environment="LIVE", payment_status="CREATED", total_price=30, currency="USD"))
    if operation_name == "HANDOVER":
        assert operation(ctx, ident)["canHandOver"] is False
        response = handover(ctx, ident)
    else:
        response = ctx["client"].post("/nadreego/booking/action", headers=ctx["admin"],
            json={"bookedNo": "BO" + ident, "action": operation_name})
    assert response.status_code == 409 and response.json()["errorCode"] == "PAYMENT_STATE_INCONSISTENT"


def test_onboarding_disabled_and_auth_scope_preserved(external, signin):
    ctx = external
    for suffix, body in (("start", {"spotMasterId": "root"}), ("verify", {"spotMasterId": "root", "state": "unused"})):
        path = "/nadreego/shop/paypal-onboarding/" + suffix
        response = ctx["client"].post(path, headers=ctx["admin"], json=body)
        assert response.status_code == 409 and response.json()["errorCode"] == "ONLINE_PAYMENT_DISABLED"
        assert ctx["client"].post(path, json=body).status_code == 401
        assert ctx["client"].post(path, headers=signin("general"), json=body).status_code == 403
    state = ctx["client"].get("/nadreego/shop/paypal-merchant", headers=ctx["admin"], params={"spotMasterId": "root"}).json()
    assert state["onlinePaymentEnabled"] is False and state["newReservationPaymentMethod"] == EXTERNAL


def test_external_booking_ownership_and_cross_spot_guards(external, signin, monkeypatch):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    outsider = signin("outsider")
    assert ctx["client"].post("/nadreego/booking/action", headers=outsider,
        json={"bookedNo": "BO" + ident, "action": "APPROVE"}).status_code == 404
    other = {"Authorization": "Bearer " + sign_user_access(ctx["settings"], "pending-user-1")}
    assert ctx["client"].get("/api/v1/nadree/rental/reservations/" + ident, headers=other).status_code == 404
    assert ctx["client"].post("/api/v1/nadree/rental/request/cancel", headers=other, json={"reservationId": ident}).status_code == 404
    approve(ctx, ident)
    during_period(ctx, ident, monkeypatch)
    assert handover(ctx, ident, headers=outsider).status_code == 404
    assert ctx["client"].post("/nadreego/rent/approve", json={"bookedNo": "BO" + ident, "qrCode": "unused"}).status_code == 401
    assert_no_payments(ctx)


@pytest.mark.parametrize("mode", ["PAYPAL", "EXTERNAL", "UNKNOWN"])
def test_client_cannot_override_reservation_payment_method(external, mode):
    from datetime import date
    start = date.today() + timedelta(days=7)
    response = external["client"].post("/api/v1/nadree/rental/request", headers=external["headers"], json={
        "spotMasterId": "root", "modelId": "pending-model", "startDate": str(start),
        "returnDate": str(start + timedelta(days=3)), "totalPrice": 30, "currency": "USD",
        "deliveryRequested": False, "paymentMethod": mode})
    assert response.status_code == 422 and response.json()["errorCode"] == "INVALID_INPUT"
    with external["engine"].connect() as conn:
        assert conn.scalar(select(func.count()).select_from(external["tables"]["MSP_RESERVATION"])) == 0


@pytest.mark.parametrize("condition,reason", [("qr_inactive", "QR_INACTIVE"), ("qr_expired", "QR_EXPIRED"),
                                           ("vehicle_inactive", "VEHICLE_UNAVAILABLE"),
                                           ("maintenance", "VEHICLE_UNAVAILABLE")])
def test_external_payment_does_not_bypass_vehicle_or_qr_guards(external, monkeypatch, condition, reason):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    approved = approve(ctx, ident)
    at = during_period(ctx, ident, monkeypatch)
    with ctx["engine"].begin() as conn:
        if condition.startswith("qr_"):
            table = ctx["tables"]["MSP_VEHICLE_QR"]
            values = {"qr_status": "INACTIVE"} if condition == "qr_inactive" else {"expired_at": at - timedelta(seconds=1)}
        elif condition == "vehicle_inactive":
            table, values = ctx["tables"]["MSP_VEHICLE"], {"is_active": 0}
        else:
            table, values = ctx["tables"]["MSP_VEHICLE_STATUS"], {"status": "MAINTENANCE", "maintenance_until": (at + timedelta(days=1)).date()}
        conn.execute(table.update().where(table.c.vehicle_id == approved["assigned_vehicle_id"]).values(**values))
    for data in (operation(ctx, ident), calendar_event(ctx, ident)):
        assert data["canHandOver"] is False and "RENT_APPROVE" not in data["availableActions"]
    response = handover(ctx, ident)
    assert response.status_code >= 400 and response.json()["errorCode"] == reason
    assert row(ctx, ident)["reservation_status"] == "APPROVED"
    assert_no_payments(ctx)


def test_unknown_stored_payment_mode_never_bypasses_payment_checks(external, monkeypatch):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    during_period(ctx, ident, monkeypatch)
    table = ctx["tables"]["MSP_RESERVATION"]
    criteria = row(ctx, ident)["required_criteria_json"]
    criteria["paymentMethod"] = "UNKNOWN"
    with ctx["engine"].begin() as conn:
        conn.execute(table.update().where(table.c.reservation_id == ident).values(required_criteria_json=criteria))
    response = handover(ctx, ident)
    assert response.status_code == 409 and response.json()["errorCode"] == "RESERVATION_PAYMENT_METHOD_INVALID"
    assert_no_payments(ctx)
