from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.rental_schema import metadata
from app.security import sign_user_access


@pytest.fixture
def cancellation(setup, monkeypatch):
    metadata.create_all(setup["engine"])
    at = datetime(2026, 10, 8, 15, 59, 59)
    monkeypatch.setattr("app.customer_rentals.now", lambda: at)
    monkeypatch.setattr("app.rentals.now", lambda: at)
    calls = []

    class PayPal:
        settings = setup["settings"]

        def for_merchant(self, merchant_id):
            return self

        def refund(self, capture_id, request_id, currency, amount):
            calls.append((capture_id, currency, amount))
            return {"id": "refund-1", "status": "COMPLETED", "amount": {"currency_code": currency, "value": str(amount)}}

        def close(self):
            pass

    setup["app"].state.paypal = PayPal()
    with setup["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RENTAL_USER"].insert().values(uid_token="customer"))
        conn.execute(metadata.tables["MSP_RESERVATION"].insert().values(
            reservation_id="cancel-1", uid_token="customer", spot_master_id="root", model_id="model-1",
            start_datetime=datetime(2026, 10, 8, 16), end_datetime=datetime(2026, 10, 10, 16),
            reservation_status="APPROVED", vehicle_assignment_status="PROVISIONAL",
            assigned_vehicle_id="vehicle-1"))
        conn.execute(metadata.tables["MSP_RENTAL_PAYMENT"].insert().values(
            reservation_id="cancel-1", payment_environment="SANDBOX", payment_status="PAID", paypal_merchant_id="SELLER1234567",
            total_price=Decimal("100"), currency="USD", paypal_capture_id="capture-1",
            paypal_order_id="order-1", paid_at=at - timedelta(hours=1)))
    return {**setup, "calls": calls, "headers": {
        "Authorization": "Bearer " + sign_user_access(setup["settings"], "customer")}}


def customer_cancel(ctx):
    return ctx["client"].post("/api/v1/nadree/rental/request/cancel", headers=ctx["headers"],
                              json={"reservationId": "cancel-1", "reason": "changed plans"})


def test_customer_paid_cancellation_before_midnight(cancellation):
    response = customer_cancel(cancellation)
    assert response.status_code == 200, response.text
    assert response.json()["refundRequestedAmount"] == 90
    assert cancellation["calls"] == [("capture-1", "USD", Decimal("90.00"))]
    with cancellation["engine"].connect() as conn:
        reservation = conn.execute(select(metadata.tables["MSP_RESERVATION"])).mappings().one()
        assert reservation["reservation_status"] == "CANCELED"
        assert reservation["assigned_vehicle_id"] is None
        payment = conn.execute(select(metadata.tables["MSP_RENTAL_PAYMENT"])).mappings().one()
        assert payment["refund_percentage"] == 90
        assert payment["cancellation_requested_by_type"] == "CUSTOMER"
        assert payment["cancellation_requested_by_id"] == "customer"
    assert customer_cancel(cancellation).status_code == 409
    assert len(cancellation["calls"]) == 1


@pytest.mark.parametrize("at", [datetime(2026, 10, 8, 16), datetime(2026, 10, 9, 16)])
@pytest.mark.parametrize("paid", [True, False])
def test_customer_cancels_without_refund_on_or_after_local_rental_day(cancellation, monkeypatch, at, paid):
    monkeypatch.setattr("app.customer_rentals.now", lambda: at)
    if not paid:
        with cancellation["engine"].begin() as conn:
            conn.execute(metadata.tables["MSP_RENTAL_PAYMENT"].delete())
    response = customer_cancel(cancellation)
    assert response.status_code == 200, response.text
    assert response.json()["refundRequestedAmount"] == 0
    assert response.json()["refundStatus"] == "NOT_REQUIRED"
    assert not cancellation["calls"]
    with cancellation["engine"].connect() as conn:
        assert conn.scalar(select(metadata.tables["MSP_RESERVATION"].c.reservation_status)) == "CANCELED"
        if paid:
            payment = conn.execute(select(metadata.tables["MSP_RENTAL_PAYMENT"])).mappings().one()
            assert payment["cancellation_requested_by_type"] == "CUSTOMER"
            assert payment["cancellation_requested_by_id"] == "customer"
            assert payment["refund_percentage"] == 0


@pytest.mark.parametrize("start", [datetime(2026, 10, 8, 16), datetime(2026, 10, 7, 16)])
def test_admin_refunds_full_amount_before_handover_including_rental_day(cancellation, signin, start):
    with cancellation["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RESERVATION"].update().values(start_datetime=start))
    response = cancellation["client"].post("/nadreego/booking/action", headers=signin(),
        json={"bookedNo": "BOcancel-1", "action": "CANCEL"})
    assert response.status_code == 200, response.text
    assert cancellation["calls"] == [("capture-1", "USD", Decimal("100.00"))]
    with cancellation["engine"].connect() as conn:
        payment = conn.execute(select(metadata.tables["MSP_RENTAL_PAYMENT"])).mappings().one()
    assert payment["cancellation_requested_by_type"] == "ADMIN"
    assert payment["cancellation_requested_by_id"] == "primary"
    assert payment["refund_percentage"] == 100
    repeated = cancellation["client"].post("/nadreego/booking/action", headers=signin(),
        json={"bookedNo": "BOcancel-1", "action": "CANCEL"})
    assert repeated.status_code == 409
    assert len(cancellation["calls"]) == 1


def test_customer_cannot_cancel_another_users_booking(cancellation):
    with cancellation["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RESERVATION"].update().values(uid_token="other"))
    assert customer_cancel(cancellation).status_code == 404
    assert not cancellation["calls"]


def test_customer_pending_capture_blocks_cancellation(cancellation):
    with cancellation["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RENTAL_PAYMENT"].update().values(payment_status="PENDING", paid_at=None))
    response = customer_cancel(cancellation)
    assert response.status_code == 409
    assert "PAYMENT_IN_PROGRESS" in response.text
    assert not cancellation["calls"]


def test_unpaid_customer_cancellation_does_not_refund(cancellation):
    with cancellation["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RENTAL_PAYMENT"].update().values(
            payment_status="CREATED", paid_at=None, paypal_capture_id=None))
    response = customer_cancel(cancellation)
    assert response.status_code == 200, response.text
    assert response.json()["refundStatus"] == "NOT_REQUIRED"
    assert response.json()["refundRequestedAmount"] == 0
    assert not cancellation["calls"]


def test_partial_refund_only_requests_remaining_customer_amount(cancellation):
    with cancellation["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RENTAL_PAYMENT"].update().values(
            payment_status="PARTIALLY_REFUNDED", refunded_amount=Decimal("20")))
    assert customer_cancel(cancellation).status_code == 200
    assert cancellation["calls"] == [("capture-1", "USD", Decimal("70.00"))]


def test_admin_cancellation_at_exact_local_midnight(cancellation, signin, monkeypatch):
    monkeypatch.setattr("app.rentals.now", lambda: datetime(2026, 10, 8, 16))
    response = cancellation["client"].post("/nadreego/booking/action", headers=signin(),
        json={"bookedNo": "BOcancel-1", "action": "CANCEL"})
    assert response.status_code == 200, response.text
    with cancellation["engine"].connect() as conn:
        assert conn.scalar(select(metadata.tables["MSP_RESERVATION"].c.reservation_status)) == "CANCELED"
    assert cancellation["calls"] == [("capture-1", "USD", Decimal("100.00"))]


def test_admin_cannot_cancel_after_handover(cancellation, signin):
    with cancellation["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RENTAL_CONTRACT"].insert().values(
            rental_contract_id="handed", reservation_id="cancel-1", uid_token="customer", vehicle_id="vehicle-1",
            pickup_spot_master_id="root", planned_end_date=datetime(2026, 10, 10).date()))
    response = cancellation["client"].post("/nadreego/booking/action", headers=signin(),
        json={"bookedNo": "BOcancel-1", "action": "CANCEL"})
    assert response.status_code == 409
    assert not cancellation["calls"]


def test_customer_cannot_cancel_after_handover(cancellation):
    with cancellation["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RENTAL_CONTRACT"].insert().values(
            rental_contract_id="handed", reservation_id="cancel-1", uid_token="customer", vehicle_id="vehicle-1",
            pickup_spot_master_id="root", planned_end_date=datetime(2026, 10, 10).date()))
    response = customer_cancel(cancellation)
    assert response.status_code == 409 and response.json()["errorCode"] == "RESERVATION_ALREADY_HANDED_OVER"
    assert not cancellation["calls"]
