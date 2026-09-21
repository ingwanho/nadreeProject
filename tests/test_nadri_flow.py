from datetime import date, timedelta
import hashlib
import hmac

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table
from sqlalchemy.orm import Session
from pydantic import SecretStr

from app.fcm import queue_payment_complete
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
    client = setup["client"]
    login = client.post("/api/v1/nadree/user/login", json={"UID": "user-flow", "fcmToken": "customer-device"})
    assert login.status_code == 200, login.text
    customer_headers = {"Authorization": "Bearer " + login.json()["accessToken"]}
    availability = client.post("/api/v1/nadree/rental/availability", headers=customer_headers, json={
        "startDate": start.isoformat(), "returnDate": end.isoformat(), "cc": 125, "deliveryRequested": False})
    assert availability.status_code == 200, availability.text
    assert availability.json()["items"], availability.text
    price = availability.json()["items"][0]["price"]["totalFrom"]
    request = client.post("/api/v1/nadree/rental/request", headers=customer_headers, json={
        "spotMasterId": "root", "modelId": "model-125", "startDate": start.isoformat(),
        "returnDate": end.isoformat(), "totalPrice": price, "currency": "USD", "deliveryRequested": False})
    assert request.status_code == 200, request.text
    reservation_id = request.json()["reservationId"]
    assert any(item["event"] == "RESERVATION_REQUESTED" and item["recipients"][0]["token"] == "admin-device"
               for item in fcm.notifications)

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
    assert any(item["event"] == "PAYMENT_COMPLETED" and item["recipients"][0]["token"] == "admin-device"
               for item in fcm.notifications)
    assert any(item["event"] == "PAYMENT_COMPLETED" and item["recipients"][0]["token"] == "customer-device"
               for item in fcm.notifications)
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
