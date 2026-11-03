from datetime import timedelta
import uuid

import pytest
from sqlalchemy import func, select

from app.receipt import expire_receipts
from app.security import now, sign_user_access
from test_external_reservations import external, row, approve, during_period, operation, calendar_event
from test_pending_reservation_approval import pending_bookings

BASE = "/api/v1/nadree/rental"


@pytest.fixture
def receipt(external):
    return external


def at_period(ctx, ident, monkeypatch):
    at = during_period(ctx, ident, monkeypatch)
    monkeypatch.setattr("app.receipt.now", lambda: at)
    monkeypatch.setattr("app.customer_qr.now", lambda: at)
    return at


def prepare(ctx, ident, *, required=True):
    r = row(ctx, ident)
    body = {"bookedNo": "BO" + ident, "qrCode": ctx["qrs"][r["assigned_vehicle_id"]]}
    if required:
        body["receiptRequired"] = True
    return ctx["client"].post("/nadreego/rent/approve", headers=ctx["admin"], json=body)


def receive(ctx, ident, qr=None, headers=None):
    return ctx["client"].post(BASE + "/reservations/" + ident + "/receive", headers=headers or ctx["headers"],
        json={"qrCode": qr or ctx["qrs"][row(ctx, ident)["assigned_vehicle_id"]]})


def count(ctx, table):
    with ctx["engine"].connect() as conn:
        return conn.scalar(select(func.count()).select_from(ctx["db"].table(table)))


def new_quote(ctx, qr=None, days=1):
    from app.rental_common import local_date
    from types import SimpleNamespace
    today = local_date(SimpleNamespace(app=ctx["app"]), now())
    body = {"qrCode": qr or next(iter(ctx["qrs"].values())), "returnDate": str(today + timedelta(days=days))}
    response = ctx["client"].post(BASE + "/onsite/quote", headers=ctx["headers"], json=body)
    assert response.status_code == 200, response.text
    return body, response.json()


def submit(ctx, body, quote, key=None):
    return ctx["client"].post(BASE + "/onsite/requests", headers=ctx["headers"], json={
        **body, "quoteToken": quote["quoteToken"], "clientRequestId": key or str(uuid.uuid4())})


def test_onsite_request_quote_idempotence_and_qr_case_preservation(receipt):
    ctx = receipt
    body, quote = new_quote(ctx)
    key = str(uuid.uuid4())
    created = submit(ctx, body, quote, key)
    assert created.status_code == 200, created.text
    item = created.json()["item"]
    ident = item["reservationId"]
    assert item["requestType"] == "ONSITE" and item["reservationStatus"] == "REQUESTED"
    assert item["payment"] is None and item["price"]["finalTotal"] == 10
    assert submit(ctx, body, quote, key).json()["item"]["reservationId"] == ident
    changed_qr = submit(ctx, {**body, "qrCode": body["qrCode"].upper()}, quote, key)
    assert changed_qr.json()["errorCode"] == "REQUEST_KEY_REUSED"
    found = ctx["client"].get(BASE + "/onsite/requests/" + key, headers=ctx["headers"])
    assert found.status_code == 200 and found.json()["item"]["reservationId"] == ident
    assert count(ctx, "MSP_RESERVATION") == 1
    other_qr = next(raw for raw in ctx["qrs"].values() if raw != body["qrCode"])
    changed, changed_quote = new_quote(ctx, qr=other_qr, days=2)
    assert submit(ctx, changed, changed_quote, key).json()["errorCode"] == "REQUEST_KEY_REUSED"
    lower = ctx["client"].post(BASE + "/qr/lookup", headers=ctx["headers"], json={"qrCode": body["qrCode"].upper()})
    assert lower.status_code == 404
    approved = approve(ctx, ident)
    assert approved["assigned_vehicle_id"] == quote["vehicleId"]
    wrong = ctx["client"].post("/nadreego/rent/approve", headers=ctx["admin"], json={
        "bookedNo": "BO" + ident, "qrCode": other_qr, "receiptRequired": True})
    assert wrong.json()["errorCode"] == "RESERVATION_VEHICLE_MISMATCH"
    lookup = ctx["client"].post(BASE + "/qr/lookup", headers=ctx["headers"], json=body | {"returnDate": None})
    assert lookup.status_code == 422  # No undocumented input fields.
    assert count(ctx, "MSP_RENTAL_PAYMENT") == 0


def test_two_phase_handover_customer_receipt_and_return(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approved = approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    assert prepare(ctx, ident, required=False).json()["errorCode"] == "CLIENT_UPDATE_REQUIRED"
    result = prepare(ctx, ident)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["reservationStatus"] == "HANDOVER_PENDING"
    assert count(ctx, "MSP_RENTAL_CONTRACT") == 0
    initial = row(ctx, ident)
    assert initial["assigned_vehicle_id"] == approved["assigned_vehicle_id"]
    assert prepare(ctx, ident).json()["data"]["receiptDeadline"] == result.json()["data"]["receiptDeadline"]
    pushes = [n for n in ctx["fcm"].notifications if n["event"] == "CUSTOMER_RECEIPT_REQUIRED"]
    assert len(pushes) == 1 and "qrCode" not in pushes[0]["data"]
    assert "RENT_APPROVE" not in operation(ctx, ident)["availableActions"]
    assert calendar_event(ctx, ident)["status"] == "HANDOVER_PENDING"
    scanned = ctx["client"].post("/nadreego/vehicle/qr/validate", headers=ctx["admin"], json={
        "qrCode": ctx["qrs"][initial["assigned_vehicle_id"]]}).json()["data"]
    assert scanned["currentBooking"]["reservationStatus"] == "HANDOVER_PENDING"
    assert scanned["availableActions"] == ["RECOVER_VEHICLE"]
    location = ctx["client"].post("/nadreego/vehicle/location", headers=ctx["admin"], json={
        "vehicleNumber": scanned["vehicle"]["vehicleNo"]})
    assert location.json()["errorCode"] == "SENSOR_NOT_LINKED"  # Read access still uses the existing sensor check.
    assert ctx["client"].post(BASE + "/request/cancel", headers=ctx["headers"], json={"reservationId": ident}).status_code == 409
    result = receive(ctx, ident)
    assert result.status_code == 200, result.text
    assert result.json()["item"]["rentalStatus"] == "ON_RENT"
    assert result.json()["item"]["receivedAt"] is not None
    lookup = ctx["client"].post(BASE + "/qr/lookup", headers=ctx["headers"], json={
        "qrCode": ctx["qrs"][initial["assigned_vehicle_id"]], "reservationId": ident})
    assert lookup.json()["receivedAt"] == result.json()["item"]["receivedAt"]
    assert receive(ctx, ident).json()["item"]["rentalContractId"] == result.json()["item"]["rentalContractId"]
    assert count(ctx, "MSP_RENTAL_CONTRACT") == 1
    returned = ctx["client"].post("/nadreego/vehicle/return", headers=ctx["admin"],
        json={"qrCode": ctx["qrs"][initial["assigned_vehicle_id"]]})
    assert returned.status_code == 200, returned.text
    assert row(ctx, ident)["reservation_status"] == "RETURNED"


def test_receipt_deadline_holds_vehicle_until_explicit_recovery(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    assert prepare(ctx, ident).status_code == 200
    r = row(ctx, ident)
    monkeypatch.setattr("app.customer_qr.now", lambda: r["receipt_deadline_at"])
    assert receive(ctx, ident).json()["errorCode"] == "RECEIPT_DEADLINE_EXPIRED"
    assert expire_receipts(ctx["db"], ctx["settings"], at=r["receipt_deadline_at"]) == 1
    assert row(ctx, ident)["reservation_status"] == "EXPIRED"
    assert row(ctx, ident)["assigned_vehicle_id"] == r["assigned_vehicle_id"]
    state = ctx["tables"]["MSP_VEHICLE_STATUS"]
    with ctx["engine"].connect() as conn:
        assert conn.scalar(select(state.c.status).where(state.c.vehicle_id == r["assigned_vehicle_id"])) == "DISABLED"
    raw = ctx["qrs"][r["assigned_vehicle_id"]]
    assert ctx["client"].post("/nadreego/vehicle/return", headers=ctx["admin"], json={"qrCode": raw}).json()["errorCode"] == "VEHICLE_RECEIPT_HOLD"
    path = "/nadreego/booking/BO" + ident + "/receipt-recovery"
    assert ctx["client"].post(path, headers=ctx["admin"], json={"qrCode": raw, "reason": "Keys returned"}).status_code == 422
    recovered = ctx["client"].post(path, headers=ctx["admin"], json={"qrCode": raw, "vehicleReturned": True, "reason": "Keys returned"})
    assert recovered.status_code == 200, recovered.text
    assert row(ctx, ident)["vehicle_assignment_status"] == "RELEASED"
    assert count(ctx, "MSP_RENTAL_PAYMENT") == 0


def test_owner_vehicle_and_pre_handover_checks(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    assert receive(ctx, ident).json()["errorCode"] == "NOT_AWAITING_RECEIPT"
    assert prepare(ctx, ident).status_code == 200
    other = {"Authorization": "Bearer " + sign_user_access(ctx["settings"], "pending-user-1")}
    assert receive(ctx, ident, headers=other).status_code == 404
    wrong = next(raw for vehicle, raw in ctx["qrs"].items() if vehicle != row(ctx, ident)["assigned_vehicle_id"])
    assert receive(ctx, ident, qr=wrong).json()["errorCode"] == "RESERVATION_VEHICLE_MISMATCH"
    assert count(ctx, "MSP_RENTAL_CONTRACT") == 0


def test_onsite_requests_expire_without_a_physical_hold(receipt):
    ctx = receipt
    body, quote = new_quote(ctx)
    response = submit(ctx, body, quote)
    ident = response.json()["item"]["reservationId"]
    assert expire_receipts(ctx["db"], ctx["settings"], at=row(ctx, ident)["hold_expires_at"]) == 1
    assert row(ctx, ident)["vehicle_assignment_status"] == "RELEASED"
    assert count(ctx, "MSP_RENTAL_CONTRACT") == 0


def test_receipt_is_always_available_and_manual_walkin_waits_for_customer(receipt):
    ctx = receipt
    response = ctx["client"].post(BASE + "/qr/lookup", headers=ctx["headers"], json={"qrCode": next(iter(ctx["qrs"].values()))})
    assert response.status_code == 200 and response.json()["availableActions"] == ["ONSITE_QUOTE"]
    from app.rental_common import local_date
    from types import SimpleNamespace
    end = local_date(SimpleNamespace(app=ctx["app"]), now()) + timedelta(days=1)
    response = ctx["client"].post("/nadreego/rent/approve", headers=ctx["admin"], json={
        "uidToken": "pending-user-0", "plannedEndDate": str(end), "qrCode": next(iter(ctx["qrs"].values())), "receiptRequired": True})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["reservationStatus"] == "HANDOVER_PENDING"
    assert count(ctx, "MSP_RENTAL_CONTRACT") == 0


def test_quote_expiry_signature_and_owner(receipt, monkeypatch):
    ctx = receipt
    body, quote = new_quote(ctx)
    broken = {**quote, "quoteToken": quote["quoteToken"] + "bad"}
    assert submit(ctx, body, broken).json()["errorCode"] == "ONSITE_QUOTE_INVALID"
    other = {"Authorization": "Bearer " + sign_user_access(ctx["settings"], "pending-user-1")}
    response = ctx["client"].post(BASE + "/onsite/requests", headers=other, json={
        **body, "quoteToken": quote["quoteToken"], "clientRequestId": str(uuid.uuid4())})
    assert response.json()["errorCode"] == "ONSITE_QUOTE_INVALID"
    later = now() + timedelta(minutes=11)
    monkeypatch.setattr("app.customer_qr.now", lambda: later)
    assert submit(ctx, body, quote).json()["errorCode"] == "ONSITE_QUOTE_EXPIRED"
    assert count(ctx, "MSP_RESERVATION") == 0


def test_successful_request_replays_after_quote_expiry(receipt, monkeypatch):
    ctx = receipt
    body, quote = new_quote(ctx)
    key = str(uuid.uuid4())
    first = submit(ctx, body, quote, key)
    later = now() + timedelta(days=1)
    monkeypatch.setattr("app.customer_qr.now", lambda: later)
    repeated = submit(ctx, body, quote, key)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["item"]["reservationId"] == first.json()["item"]["reservationId"]
    assert count(ctx, "MSP_RESERVATION") == 1


def test_price_change_requires_new_confirmation(receipt):
    ctx = receipt
    body, quote = new_quote(ctx)
    table = ctx["tables"]["MSP_RENTAL_TIER"]
    with ctx["engine"].begin() as conn:
        conn.execute(table.update().values(price=11))
    assert submit(ctx, body, quote).json()["errorCode"] == "ONSITE_QUOTE_CHANGED"
    assert count(ctx, "MSP_RESERVATION") == 0


def test_hold_blocks_vehicle_mutations_and_expiry_is_idempotent(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    assert prepare(ctx, ident).status_code == 200
    r = row(ctx, ident)
    rv = ctx["tables"]["MSP_RENTAL_VEHICLE"]
    with ctx["engine"].connect() as conn:
        plate = conn.scalar(select(rv.c.plate_number_full).where(rv.c.vehicle_id == r["assigned_vehicle_id"]))
    response = ctx["client"].post("/nadreego/vehicle/spotChange", headers=ctx["admin"],
        json={"vehicleNumber": plate, "spotCode": "child"})
    assert response.json()["errorCode"] == "VEHICLE_RECEIPT_HOLD"
    assert expire_receipts(ctx["db"], ctx["settings"], at=r["receipt_deadline_at"]) == 1
    assert expire_receipts(ctx["db"], ctx["settings"], at=r["receipt_deadline_at"]) == 0
    assert "RECOVER_VEHICLE" in operation(ctx, ident)["availableActions"]


def test_obsolete_false_setting_cannot_disable_customer_receipt(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    assert prepare(ctx, ident).status_code == 200
    from app.config import Settings
    monkeypatch.setenv("NADREE_CUSTOMER_RECEIPT_ENABLED", "false")
    ctx["app"].state.settings = Settings(_env_file=None, **ctx["settings"].model_dump())
    assert "customer_receipt_enabled" not in Settings.model_fields
    lookup = ctx["client"].post(BASE + "/qr/lookup", headers=ctx["headers"], json={
        "qrCode": ctx["qrs"][row(ctx, ident)["assigned_vehicle_id"]], "reservationId": ident})
    assert lookup.status_code == 200 and lookup.json()["canReceive"] is True
    assert receive(ctx, ident).status_code == 200


def test_receipt_response_loss_does_not_restart_after_qr_expiry(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    prepare(ctx, ident)
    assert receive(ctx, ident).status_code == 200
    with ctx["engine"].begin() as conn:
        q = ctx["tables"]["MSP_VEHICLE_QR"]
        conn.execute(q.update().values(qr_status="INACTIVE"))
    assert receive(ctx, ident).status_code == 200
    assert count(ctx, "MSP_RENTAL_CONTRACT") == 1


def test_failed_push_does_not_undo_handover(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    def failed(*args):
        raise RuntimeError("isolated notification failure")
    monkeypatch.setattr(ctx["fcm"], "dispatch", failed)
    assert prepare(ctx, ident).status_code == 200
    assert row(ctx, ident)["reservation_status"] == "HANDOVER_PENDING"
    assert count(ctx, "MSP_RENTAL_CONTRACT") == 0


def test_onsite_mode_does_not_enable_paypal(receipt):
    ctx = receipt
    ctx["settings"].reservation_payment_method = "PAYPAL"
    body, quote = new_quote(ctx)
    created = submit(ctx, body, quote)
    assert created.status_code == 200
    assert created.json()["item"]["paymentMethod"] == "EXTERNAL"
    assert created.json()["item"]["payment"] is None


def test_customer_lookup_does_not_expose_other_customer_reservation(receipt):
    ctx = receipt
    body, quote = new_quote(ctx)
    ident = submit(ctx, body, quote).json()["item"]["reservationId"]
    other = {"Authorization": "Bearer " + sign_user_access(ctx["settings"], "pending-user-1")}
    response = ctx["client"].post(BASE + "/qr/lookup", headers=other, json={"qrCode": body["qrCode"]})
    assert response.status_code == 200 and response.json()["reservationId"] is None
    assert "uidToken" not in response.text and ident not in response.text
    response = ctx["client"].post(BASE + "/qr/lookup", headers=other, json={
        "qrCode": body["qrCode"], "reservationId": ident})
    assert response.status_code == 404


def test_old_client_cannot_skip_customer_confirmation(external, monkeypatch):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    response = prepare(ctx, ident, required=False)
    assert response.json()["errorCode"] == "CLIENT_UPDATE_REQUIRED"
    assert count(ctx, "MSP_RENTAL_CONTRACT") == 0


def test_existing_rental_is_not_required_to_receive_again(external, monkeypatch):
    ctx = external
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    assert prepare(ctx, ident).status_code == 200
    assert receive(ctx, ident).status_code == 200
    # A migrated contract has no administrator/customer receipt timestamps.
    reservation = ctx["tables"]["MSP_RESERVATION"]
    with ctx["engine"].begin() as conn:
        conn.execute(reservation.update().where(reservation.c.reservation_id == ident).values(
            handed_over_at=None, receipt_deadline_at=None))
    result = ctx["client"].get(BASE + "/reservations/" + ident, headers=ctx["headers"]).json()["item"]
    assert result["rentalStatus"] == "ON_RENT" and result["customerReceiptRequired"] is False
    assert result["canReceive"] is False


def test_expired_handover_cannot_be_quoted_or_reassigned(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    prepare(ctx, ident)
    held = row(ctx, ident)
    expire_receipts(ctx["db"], ctx["settings"], at=held["receipt_deadline_at"])
    response = ctx["client"].post(BASE + "/onsite/quote", headers=ctx["headers"], json={
        "qrCode": ctx["qrs"][held["assigned_vehicle_id"]], "returnDate": str(held["end_datetime"].date())})
    assert response.status_code == 409
    assert row(ctx, ident)["assigned_vehicle_id"] == held["assigned_vehicle_id"]
    assert calendar_event(ctx, ident)["isBlocking"] is True


def test_admin_read_views_share_receipt_identifiers_and_keep_expired_work(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at = at_period(ctx, ident, monkeypatch)
    monkeypatch.setattr("app.readmodels.now", lambda: at)
    assert prepare(ctx, ident).status_code == 200
    held = row(ctx, ident)
    scanned = ctx["client"].post("/nadreego/vehicle/qr/validate", headers=ctx["admin"],
        json={"qrCode": ctx["qrs"][held["assigned_vehicle_id"]]}).json()["data"]
    assert scanned["currentBooking"]["reservationId"] == ident
    assert scanned["currentBooking"]["vehicleId"] == held["assigned_vehicle_id"]
    operation_item = operation(ctx, ident)
    assert operation_item["reservationId"] == operation_item["reservation"]["reservationId"] == ident
    assert operation_item["vehicleId"] == operation_item["vehicle"]["vehicleId"] == held["assigned_vehicle_id"]
    home = ctx["client"].get("/nadreego/main", headers=ctx["admin"]).json()
    work = next(r for r in home["todayWork"] if r.get("reservationId") == ident)
    assert work["requestType"] == "ADVANCE" and work["receiptDeadline"] is not None
    assert work["availableActions"] == ["RECOVER_VEHICLE"] and work["canHandOver"] is False
    expire_receipts(ctx["db"], ctx["settings"], at=held["receipt_deadline_at"])
    after_original_end = held["end_datetime"] + timedelta(days=2)
    monkeypatch.setattr("app.readmodels.now", lambda: after_original_end)
    monkeypatch.setattr("app.receipt.now", lambda: after_original_end)
    home = ctx["client"].get("/nadreego/main", headers=ctx["admin"]).json()
    work = next(r for r in home["todayWork"] if r.get("reservationId") == ident)
    assert work["reservationStatus"] == "EXPIRED" and work["vehicleRecoveryRequired"] is True
    assert work["receiptBlockedReason"] == "RECEIPT_DEADLINE_EXPIRED"
    assert work["availableActions"] == ["RECOVER_VEHICLE"]


def test_admin_home_has_contract_and_return_action_after_customer_receipt(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at = at_period(ctx, ident, monkeypatch)
    monkeypatch.setattr("app.readmodels.now", lambda: at)
    prepare(ctx, ident)
    received = receive(ctx, ident).json()["item"]
    home = ctx["client"].get("/nadreego/main", headers=ctx["admin"]).json()
    work = next(r for r in home["todayWork"] if r.get("reservationId") == ident)
    assert work["rentalStatus"] == "ON_RENT" and "RETURN" in work["availableActions"]
    assert work["rental"]["rentalContractId"] == received["rentalContractId"]


@pytest.mark.mysql
def test_mysql_duplicate_onsite_submission_creates_only_one_reservation(receipt):
    from test_mysql_concurrency import race
    ctx = receipt
    body, quote = new_quote(ctx)
    key = str(uuid.uuid4())
    results = race(lambda _: submit(ctx, body, quote, key), [0, 1])
    assert [r.status_code for r in results] == [200, 200]
    assert len({r.json()["item"]["reservationId"] for r in results}) == 1
    assert count(ctx, "MSP_RESERVATION") == 1


@pytest.mark.mysql
def test_mysql_customer_receipt_creates_only_one_contract(receipt, monkeypatch):
    from test_mysql_concurrency import race
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approve(ctx, ident)
    at_period(ctx, ident, monkeypatch)
    assert prepare(ctx, ident).status_code == 200
    results = race(lambda _: receive(ctx, ident), [0, 1])
    assert [r.status_code for r in results] == [200, 200]
    assert len({r.json()["item"]["rentalContractId"] for r in results}) == 1
    assert count(ctx, "MSP_RENTAL_CONTRACT") == 1
