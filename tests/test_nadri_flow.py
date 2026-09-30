from datetime import date, timedelta
import hashlib
import hmac

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table
from sqlalchemy.orm import Session
from pydantic import SecretStr

from app.fcm import _manager_recipients, queue_payment_complete
from app.rental_schema import metadata as rental_metadata
from app.security import now


class FakePayPal:
    environment = "SANDBOX"

    def create_order(self, request_id, currency, value, reference_id):
        return {"id": "ORDER-1", "status": "CREATED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1"}]}

    def approval_url(self, order):
        return order["links"][0]["href"]

    def capture_order(self, order_id, request_id):
        return {"id": order_id, "status": "COMPLETED",
                "purchase_units": [{"payments": {"captures": [{"id": "CAPTURE-1", "status": "COMPLETED"}]}}]}

    def capture_reference_from_order(self, order):
        return order["purchase_units"][0]["payments"]["captures"][0]["id"]

    def close(self):
        pass


class RecordingFcm:
    def __init__(self):
        self.notifications = []

    def dispatch(self, db, notifications):
        self.notifications.extend(notifications)

    def close(self):
        pass


def test_manager_fcm_recipients_include_parent_and_child_scope(setup):
    admins = setup["db"].table("MSP_ADMIN")
    roles = setup["db"].table("MSP_ADMIN_ROLE")
    scopes = setup["db"].table("MSP_ADMIN_SPOT_SCOPE")
    with setup["engine"].begin() as conn:
        conn.execute(admins.insert().values(
            admin_id="child-manager", login_id="child-manager@example.com",
            email="child-manager@example.com", admin_name="child-manager",
            password_hash="test-hash", mfa_method="none", contract_id="CT1",
            primary_spot_master_id="child", is_active=1, fcm_token="child-device"))
        conn.execute(roles.insert().values(
            admin_id="child-manager", role_code="rental_manager", assigned_at=now()))
        conn.execute(scopes.insert().values(
            admin_id="child-manager", spot_master_id="child", access_type="manage"))
        conn.execute(admins.update().where(admins.c.admin_id == "primary").values(fcm_token="parent-device"))
    with Session(setup["engine"]) as session:
        recipients = _manager_recipients(setup["db"], session, "child")
    assert {item["token"] for item in recipients} == {"parent-device", "child-device"}


def prepare_rental_schema(setup):
    engine, db = setup["engine"], setup["db"]
    rental_metadata.create_all(engine)
    extra = MetaData()
    Table("MSP_VEHICLE", extra,
          Column("vehicle_id", String(36), primary_key=True), Column("plate_number", String(25)),
          Column("is_active", Integer, nullable=False, default=1))
    Table("MSP_VEHICLE_SPOT_HISTORY", extra,
          Column("history_id", Integer, primary_key=True, autoincrement=True), Column("vehicle_id", String(36), nullable=False),
          Column("spot_master_id", String(36), nullable=False), Column("released_at", DateTime))
    Table("MSP_SENSOR", extra,
          Column("sensor_id", String(36), primary_key=True), Column("vehicle_id", String(36), nullable=False),
          Column("is_active", Integer, nullable=False, default=1))
    extra.create_all(engine)
    for name in ("MSP_VEHICLE", "MSP_VEHICLE_SPOT_HISTORY", "MSP_SENSOR"):
        db.table(name)
    return {name: db.table(name) for name in (
        "MSP_RENTAL_USER", "MSP_VEHICLE_MODEL", "MSP_RENTAL_VEHICLE", "MSP_VEHICLE_STATUS",
        "MSP_VEHICLE_QR", "MSP_RESERVATION", "MSP_RESERVATION_HISTORY", "MSP_RENTAL_CONTRACT",
        "MSP_RENTAL_CONTRACT_HISTORY", "MSP_RENTAL_TIER", "MSP_RENTAL_PAYMENT", "MSP_VEHICLE",
        "MSP_VEHICLE_SPOT_HISTORY", "MSP_SENSOR")}


def test_nadri_reservation_payment_checkout_and_return(setup, signin):
    tables = prepare_rental_schema(setup)
    settings = setup["settings"]
    fcm = RecordingFcm()
    setup["app"].state.fcm = fcm
    settings.qr_hash_key = SecretStr("isolated-qr-signing-key-with-at-least-32-bytes")
    setup["app"].state.paypal = FakePayPal()
    at = date.today()
    start = at
    end = start + timedelta(days=3)
    raw_qr = "qr-rental-flow"
    qr_hash = hmac.new(settings.qr_hash_key.get_secret_value().encode(), raw_qr.encode(), hashlib.sha256).hexdigest()
    with setup["engine"].begin() as conn:
        conn.execute(tables["MSP_VEHICLE_MODEL"].insert().values(
            model_id="model-125", brand="Nadree", model_name="Scooter", cc=125,
            vehicle_type="SCOOTER", is_delivery_supported=0, is_active=1,
            created_at=now(), updated_at=now()))
        conn.execute(tables["MSP_RENTAL_VEHICLE"].insert().values(
            vehicle_id="vehicle-1", model_id="model-125", plate_number_full="B 1234 NAD",
            price_type="BASIC", rental_enabled=1, created_at=now(), updated_at=now()))
        conn.execute(tables["MSP_VEHICLE"].insert().values(vehicle_id="vehicle-1", plate_number="B 1234 NAD", is_active=1))
        conn.execute(tables["MSP_VEHICLE_SPOT_HISTORY"].insert().values(vehicle_id="vehicle-1", spot_master_id="root"))
        conn.execute(tables["MSP_VEHICLE_STATUS"].insert().values(
            vehicle_id="vehicle-1", status="AVAILABLE", status_changed_at=now(), created_at=now(), updated_at=now()))
        conn.execute(tables["MSP_VEHICLE_QR"].insert().values(
            vehicle_id="vehicle-1", qr_id="qr-1", qr_code_hash=qr_hash, qr_status="ACTIVE",
            issued_at=now(), created_at=now(), updated_at=now()))
        conn.execute(tables["MSP_RENTAL_TIER"].insert().values(
            spot_master_id="root", price=100, min_cc=0, max_cc=1000, tier_type="BASIC"))
        conn.execute(tables["MSP_RENTAL_TIER"].insert().values(
            spot_master_id=None, price=100, min_cc=0, max_cc=1000, tier_type="BASE"))
        admins = setup["db"].table("MSP_ADMIN")
        conn.execute(admins.update().where(admins.c.admin_id == "primary").values(fcm_token="admin-device"))
        conn.execute(admins.update().where(admins.c.admin_id == "general").values(fcm_token="general-device"))
        conn.execute(admins.update().where(admins.c.admin_id == "general2").values(fcm_token="general2-device"))
    client = setup["client"]
    login = client.post("/api/v1/nadree/user/login", json={"UID": "user-flow", "fcmToken": "customer-device"})
    assert login.status_code == 200, login.text
    customer_headers = {"Authorization": "Bearer " + login.json()["accessToken"]}
    availability = client.post("/api/v1/nadree/rental/availability", headers=customer_headers, json={
        "startDate": start.isoformat(), "returnDate": end.isoformat(), "cc": 125, "deliveryRequested": False})
    assert availability.status_code == 200, availability.text
    assert availability.json()["items"], availability.text
    assert availability.json()["items"][0]["shopId"] == "root"
    assert availability.json()["items"][0]["modelId"] == "model-125"
    price = availability.json()["items"][0]["price"]["totalFrom"]
    request = client.post("/api/v1/nadree/rental/request", headers=customer_headers, json={
        "spotMasterId": "root", "modelId": "model-125", "startDate": start.isoformat(),
        "returnDate": end.isoformat(), "totalPrice": price, "currency": "USD", "deliveryRequested": False})
    assert request.status_code == 200, request.text
    reservation_id = request.json()["reservationId"]
    assert request.json()["bookingId"] == reservation_id
    assert request.json()["shopId"] == "root"
    reservation_push = next(item for item in fcm.notifications if item["event"] == "RESERVATION_REQUESTED")
    assert {item["token"] for item in reservation_push["recipients"]} == {
        "admin-device", "general-device", "general2-device"}

    # A pending request holds the only vehicle for the overlapping period.
    second_login = client.post("/api/v1/nadree/user/login", json={"UID": "user-flow-second"})
    assert second_login.status_code == 200, second_login.text
    second_headers = {"Authorization": "Bearer " + second_login.json()["accessToken"]}
    blocked = client.post("/api/v1/nadree/rental/request", headers=second_headers, json={
        "spotMasterId": "root", "modelId": "model-125", "startDate": start.isoformat(),
        "returnDate": end.isoformat(), "totalPrice": price, "currency": "USD", "deliveryRequested": False})
    assert blocked.status_code == 409 and blocked.json()["errorCode"] == "RENTAL_UNAVAILABLE"

    # A legacy expiry value must not block approval now that approval has no timeout.
    with setup["engine"].begin() as conn:
        conn.execute(tables["MSP_RESERVATION"].update().where(
            tables["MSP_RESERVATION"].c.reservation_id == reservation_id).values(hold_expires_at=now() - timedelta(days=1)))
    admin_headers = signin()
    approved = client.post("/nadreego/booking/action", headers=admin_headers,
                           json={"bookedNo": "BO" + reservation_id, "action": "APPROVE"})
    assert approved.status_code == 200, approved.text
    assert any(item["event"] == "RESERVATION_APPROVED" and item["recipients"][0]["token"] == "customer-device"
               and "3일 이내" in item["body"]
               for item in fcm.notifications)

    order = client.post("/api/v1/nadree/rental/payment/order", headers=customer_headers,
                        json={"reservationId": reservation_id})
    assert order.status_code == 200, order.text
    payment_id = order.json()["paymentId"]
    captured = client.post("/api/v1/nadree/rental/payment/capture", headers=customer_headers,
                           json={"paymentId": payment_id})
    assert captured.status_code == 200, captured.text
    assert captured.json()["paymentStatus"] == "PENDING"
    recovered = client.get(f"/api/v1/nadree/rental/payment/{payment_id}", headers=customer_headers)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["paymentStatus"] == "PENDING"
    assert recovered.json()["bookingId"] == reservation_id
    assert recovered.json()["shopId"] == "root"
    blocked = client.post("/nadreego/rent/approve", headers=admin_headers,
                          json={"bookedNo": "BO" + reservation_id, "qrCode": raw_qr})
    assert blocked.status_code == 409 and blocked.json()["errorCode"] == "PAYMENT_REQUIRED"

    with setup["engine"].begin() as conn:
        payment = tables["MSP_RENTAL_PAYMENT"]
        conn.execute(payment.update().where(payment.c.payment_id == payment_id).values(
            payment_status="PAID", paypal_capture_id="CAPTURE-1", paid_at=now()))
    with Session(setup["engine"]) as session, session.begin():
        queue_payment_complete(setup["db"], session, "user-flow", reservation_id, "root", payment_id)
        payment_notifications = session.info.pop("fcm_notifications")
    fcm.dispatch(setup["db"], payment_notifications)
    payment_pushes = [item for item in fcm.notifications if item["event"] == "PAYMENT_COMPLETED"]
    assert any({recipient["token"] for recipient in item["recipients"]} >= {
        "admin-device", "general-device", "general2-device"} for item in payment_pushes)
    assert any({recipient["token"] for recipient in item["recipients"]} == {"customer-device"}
               for item in payment_pushes)
    handed_over = client.post("/nadreego/rent/approve", headers=admin_headers,
                              json={"bookedNo": "BO" + reservation_id, "qrCode": raw_qr})
    assert handed_over.status_code == 200, handed_over.text
    assert handed_over.json()["data"]["contractStatus"] == "ON_RENT"

    returned = client.post("/nadreego/vehicle/return", headers=admin_headers, json={"qrCode": raw_qr})
    assert returned.status_code == 200, returned.text
    assert returned.json()["data"]["vehicleStatus"] == "AVAILABLE"
    completed = client.get("/api/v1/nadree/rental/completed", headers=customer_headers)
    assert completed.status_code == 200, completed.text
    assert completed.json()["totalCount"] == 1
    completed_item = completed.json()["items"][0]
    assert completed_item["price"]["currency"] == "USD"
    assert completed_item["price"]["totalFrom"] == price
    assert completed_item["price"]["totalTo"] == price
    assert completed_item["price"]["rentalDays"] == (end - start).days
    assert completed_item["delivery"]["startDeliveryFee"] == 0


def test_calendar_pages_vehicle_details_before_loading_events(setup, signin):
    tables = prepare_rental_schema(setup)
    at = now()
    with setup["engine"].begin() as conn:
        for model_id, name in [("model-a", "Alpha"), ("model-b", "Beta")]:
            conn.execute(tables["MSP_VEHICLE_MODEL"].insert().values(
                model_id=model_id, brand="Nadree", model_name=name, cc=125,
                vehicle_type="SCOOTER", is_delivery_supported=0, is_active=1,
                created_at=at, updated_at=at))
        for vehicle_id, model_id, plate in [
            ("vehicle-a", "model-a", "A-100"), ("vehicle-b", "model-b", "B-200")]:
            conn.execute(tables["MSP_RENTAL_VEHICLE"].insert().values(
                vehicle_id=vehicle_id, model_id=model_id, plate_number_full=plate,
                price_type="BASIC", rental_enabled=1, created_at=at, updated_at=at))
            conn.execute(tables["MSP_VEHICLE"].insert().values(
                vehicle_id=vehicle_id, plate_number=plate, is_active=1))
            conn.execute(tables["MSP_VEHICLE_SPOT_HISTORY"].insert().values(
                vehicle_id=vehicle_id, spot_master_id="root"))
            conn.execute(tables["MSP_VEHICLE_STATUS"].insert().values(
                vehicle_id=vehicle_id, status="AVAILABLE", status_changed_at=at,
                created_at=at, updated_at=at))

    headers = signin()
    period = {"startDate": at.date().isoformat(), "endDate": (at.date() + timedelta(days=1)).isoformat()}
    first = setup["client"].post("/nadreego/main/calendar", headers=headers,
                                 json={**period, "page": 1, "pageSize": 1})
    assert first.status_code == 200, first.text
    assert first.json()["totalCount"] == 2
    assert [item["vehicleId"] for item in first.json()["items"]] == ["vehicle-a"]

    keyword = setup["client"].post("/nadreego/main/calendar", headers=headers,
                                   json={**period, "page": 1, "pageSize": 10, "keyword": "beta"})
    assert keyword.status_code == 200, keyword.text
    assert keyword.json()["totalCount"] == 1
    assert [item["vehicleId"] for item in keyword.json()["items"]] == ["vehicle-b"]

    status = setup["client"].post("/nadreego/main/calendar", headers=headers,
                                  json={**period, "page": 1, "pageSize": 1, "vehicleStatus": "AVAILABLE"})
    assert status.status_code == 200, status.text
    assert status.json()["totalCount"] == 2
    assert [item["vehicleId"] for item in status.json()["items"]] == ["vehicle-a"]
