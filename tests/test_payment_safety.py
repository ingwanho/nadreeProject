import json
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.errors import Problem
from app.jobs import expire_unpaid_payments
from app.paypal import process_event, save_event
from app.refund_recovery import execute_refund
from app.rental_schema import metadata
from app.security import now, sign_user_access


@pytest.fixture
def payments(setup):
    metadata.create_all(setup["engine"])
    at = now()
    tables = metadata.tables
    with setup["engine"].begin() as conn:
        conn.execute(tables["MSP_RENTAL_USER"].insert().values(uid_token="payment-user"))
        conn.execute(tables["MSP_RESERVATION"].insert().values(
            reservation_id="safe-booking", uid_token="payment-user", spot_master_id="root", model_id="model",
            start_datetime=at + timedelta(days=7), end_datetime=at + timedelta(days=9),
            reservation_status="APPROVED", created_at=at,
            required_criteria_json={"quote": {"currency": "USD", "totalOptions": [100], "requestedTotal": 100, "finalTotal": 100}}))

    class PayPal:
        settings = setup["settings"]

        def for_merchant(self, merchant_id):
            self.merchant_id = merchant_id
            return self

        def verify_merchant(self, merchant_id):
            pass

        def __init__(self):
            self.orders, self.captures, self.refunds = [], [], []
            self.fail_order = self.fail_capture = self.fail_refund = False
            self.order_status = "APPROVED"

        def create_order(self, key, currency, value, booking):
            self.orders.append(key)
            if self.fail_order:
                raise Problem(503, "PAYPAL_SERVICE_UNAVAILABLE")
            return self.get("orders", "safe-order")

        def get(self, resource, ident):
            assert resource == "orders"
            return {"id": ident, "status": self.order_status,
                    "purchase_units": [{"payee": {"merchant_id": self.merchant_id}}]}

        def approval_url(self, order):
            return "https://www.sandbox.paypal.com/checkoutnow?token=" + order["id"]

        def capture_order(self, ident, key):
            self.captures.append(key)
            if self.fail_capture:
                raise Problem(503, "PAYPAL_SERVICE_UNAVAILABLE")
            return {"id": ident, "status": "COMPLETED"}

        def capture_reference_from_order(self, result):
            return "safe-capture"

        def refund(self, capture, key, currency, value):
            self.refunds.append((key, value))
            if self.fail_refund:
                raise Problem(503, "PAYPAL_SERVICE_UNAVAILABLE")
            return {"id": "refund-" + str(len(self.refunds)), "status": "COMPLETED",
                    "amount": {"currency_code": currency, "value": str(value)}}

        def close(self):
            pass

    setup["app"].state.paypal = PayPal()
    return {**setup, "at": at, "pg": setup["app"].state.paypal,
            "headers": {"Authorization": "Bearer " + sign_user_access(setup["settings"], "payment-user")}}


def insert_payment(ctx, **values):
    defaults = dict(reservation_id="safe-booking", payment_environment="SANDBOX", payment_status="CREATED",
                    total_price=100, currency="USD", paypal_merchant_id="SELLER1234567")
    defaults.update(values)
    with ctx["engine"].begin() as conn:
        return conn.execute(metadata.tables["MSP_RENTAL_PAYMENT"].insert().values(**defaults)).inserted_primary_key[0]


def payment_rows(ctx):
    with ctx["engine"].connect() as conn:
        return list(conn.execute(select(metadata.tables["MSP_RENTAL_PAYMENT"]).order_by(
            metadata.tables["MSP_RENTAL_PAYMENT"].c.payment_id)).mappings())


def order(ctx):
    return ctx["client"].post("/api/v1/nadree/rental/payment/order", headers=ctx["headers"], json={"reservationId": "safe-booking"})


def capture(ctx, ident):
    return ctx["client"].post("/api/v1/nadree/rental/payment/capture", headers=ctx["headers"], json={"paymentId": ident})


@pytest.mark.parametrize("status,code", [("PAID", "PAYMENT_ALREADY_PAID"), ("PENDING", "PAYMENT_IN_PROGRESS")])
def test_older_payment_not_hidden_by_latest_attempt(payments, status, code):
    insert_payment(payments, payment_status=status)
    insert_payment(payments)
    response = order(payments)
    assert response.status_code == 409 and response.json()["errorCode"] == code
    assert not payments["pg"].orders


def test_order_timeout_keeps_identity_and_reuses_it(payments):
    payments["pg"].fail_order = True
    assert order(payments).status_code == 503
    rows = payment_rows(payments)
    assert len(rows) == 1 and rows[0]["order_requested_at"] is not None
    assert rows[0]["payment_status"] == "CREATED"
    payments["pg"].fail_order = False
    assert order(payments).status_code == 200
    assert len(payment_rows(payments)) == 1
    assert len(set(payments["pg"].orders)) == 1


def test_order_timeout_beyond_replay_window_requires_review(payments):
    insert_payment(payments, order_requested_at=now() - timedelta(hours=6))
    response = order(payments)
    assert response.status_code == 409
    assert response.json()["errorCode"] == "PAYMENT_RECONCILIATION_REQUIRED"
    assert not payments["pg"].orders


def test_capture_timeout_blocks_new_order_but_replays_same_capture(payments):
    ident = insert_payment(payments, paypal_order_id="safe-order")
    payments["pg"].fail_capture = True
    assert capture(payments, ident).status_code == 503
    row = payment_rows(payments)[0]
    assert row["capture_requested_at"] and row["payment_status"] == "PENDING"
    assert order(payments).status_code == 409
    payments["pg"].fail_capture = False
    assert capture(payments, ident).status_code == 200
    assert len(set(payments["pg"].captures)) == 1
    assert not payments["pg"].orders


def test_completed_pg_order_is_not_captured_again(payments):
    ident = insert_payment(payments, paypal_order_id="safe-order")
    payments["pg"].order_status = "COMPLETED"
    assert capture(payments, ident).status_code == 409
    assert not payments["pg"].captures


def test_capture_cannot_cross_payment_environment(payments):
    ident = insert_payment(payments, paypal_order_id="live-order", payment_environment="LIVE")
    assert capture(payments, ident).status_code == 404
    assert not payments["pg"].captures


def test_unknown_capture_is_not_expired_or_reassigned(payments):
    insert_payment(payments, payment_status="PENDING", paypal_order_id="safe-order", capture_requested_at=now())
    assert expire_unpaid_payments(payments["db"], payments["settings"], at=now() + timedelta(days=4), paypal=payments["pg"]) == 0


def test_unpaid_pg_read_failure_keeps_reservation(payments, monkeypatch):
    insert_payment(payments, paypal_order_id="safe-order")
    def fail(*args):
        raise Problem(503, "PAYPAL_SERVICE_UNAVAILABLE")
    monkeypatch.setattr(payments["pg"], "get", fail)
    assert expire_unpaid_payments(payments["db"], payments["settings"], at=now() + timedelta(days=4), paypal=payments["pg"]) == 0


def test_refund_timeout_preserves_amount_and_id_even_if_target_increases(payments, monkeypatch):
    ident = insert_payment(payments, payment_status="PAID", paid_at=now(), paypal_capture_id="capture",
                           refund_status="REQUESTED", refund_requested_amount=90)
    payments["pg"].fail_refund = True
    assert not execute_refund(payments["db"], payments["pg"], ident)
    with payments["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RENTAL_PAYMENT"].update().values(refund_requested_amount=100))
    payments["pg"].fail_refund = False
    monkeypatch.setattr("app.refund_recovery.now", lambda: payments["at"] + timedelta(minutes=10))
    assert not execute_refund(payments["db"], payments["pg"], ident)
    assert payments["pg"].refunds[0] == payments["pg"].refunds[1]
    assert payment_rows(payments)[0]["refunded_amount"] == Decimal("90")
    assert execute_refund(payments["db"], payments["pg"], ident)
    assert payments["pg"].refunds[-1][1] == Decimal("10")
    assert payment_rows(payments)[0]["refunded_amount"] == Decimal("100")


def test_refund_retries_stop_and_leave_manual_marker(payments, monkeypatch):
    ident = insert_payment(payments, payment_status="PAID", paid_at=now(), paypal_capture_id="capture",
                           refund_status="REQUESTED", refund_requested_amount=90)
    payments["pg"].fail_refund = True
    for minute in (0, 2, 7, 16, 33, 70):
        monkeypatch.setattr("app.refund_recovery.now", lambda minute=minute: payments["at"] + timedelta(minutes=minute))
        assert not execute_refund(payments["db"], payments["pg"], ident)
    assert len(payments["pg"].refunds) == 5
    assert len({key for key, _ in payments["pg"].refunds}) == 1
    assert payment_rows(payments)[0]["refund_attempt_state"]["manualRequired"] is True


def complete_event(ctx, order_id, capture_id, captured_at):
    event = {"id": "event-" + capture_id, "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": capture_id}}
    stored = save_event(ctx["db"], "SANDBOX", event, json.dumps(event), {})
    snapshot = {"order": {"id": order_id, "purchase_units": [{"payee": {"merchant_id": "SELLER1234567"}}]}, "capture": {"id": capture_id, "status": "COMPLETED",
        "create_time": captured_at.isoformat() + "Z"}, "refunds": {}, "refund": None, "amount": ("USD", Decimal("100"))}
    return process_event(ctx["db"], ctx["pg"], stored, snapshot)


@pytest.mark.parametrize("late,expected", [(True, 100), (False, 90)])
def test_actual_late_capture_vs_delayed_webhook(payments, late, expected):
    ident = insert_payment(payments, payment_status="CANCELED", paypal_order_id="safe-order", refund_status="NOT_REQUIRED",
                           refund_requested_amount=0, refund_percentage=90, cancellation_requested_by_type="CUSTOMER")
    terminal = payments["at"] + timedelta(hours=1)
    with payments["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RESERVATION"].update().values(reservation_status="CANCELED"))
        conn.execute(metadata.tables["MSP_RESERVATION_HISTORY"].insert().values(reservation_id="safe-booking",
            event_type="CANCELLED", new_reservation_status="CANCELED", created_at=terminal))
    complete_event(payments, "safe-order", "capture", terminal + timedelta(minutes=1 if late else -1))
    row = payment_rows(payments)[0]
    assert row["payment_id"] == ident and row["refund_requested_amount"] == expected
    assert row["refund_status"] == "REQUESTED"
    assert row["refund_percentage"] == expected


def test_duplicate_capture_refunds_only_extra_payment(payments):
    original = insert_payment(payments, paypal_order_id="original-order", paypal_capture_id="original-capture",
                              payment_status="PAID", paid_at=payments["at"])
    duplicate = insert_payment(payments, paypal_order_id="extra-order")
    complete_event(payments, "extra-order", "extra-capture", payments["at"] + timedelta(minutes=1))
    first, second = payment_rows(payments)
    assert first["payment_id"] == original and first["refund_status"] == "NONE"
    assert second["payment_id"] == duplicate and second["refund_requested_amount"] == 100
    assert second["refund_reason"] == "DUPLICATE_CAPTURE"


def test_failed_old_order_is_checked_before_new_order(payments):
    insert_payment(payments, payment_status="FAILED", paypal_order_id="old-order")
    assert order(payments).status_code == 409
    assert not payments["pg"].orders


def test_pending_refund_is_polled_not_submitted_again(payments, monkeypatch):
    ident = insert_payment(payments, payment_status="PAID", paid_at=now(), paypal_capture_id="capture",
                           refund_status="REQUESTED", refund_requested_amount=90)
    calls = []
    def pending(*args):
        calls.append(args)
        return {"id": "pending-refund", "status": "PENDING", "amount": {"currency_code": "USD", "value": "90.00"}}
    monkeypatch.setattr(payments["pg"], "refund", pending)
    assert not execute_refund(payments["db"], payments["pg"], ident)
    monkeypatch.setattr(payments["pg"], "get", lambda kind, ident: {
        "id": ident, "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "90.00"}})
    monkeypatch.setattr("app.refund_recovery.now", lambda: payments["at"] + timedelta(minutes=10))
    assert execute_refund(payments["db"], payments["pg"], ident)
    assert len(calls) == 1
    assert payment_rows(payments)[0]["refunded_amount"] == Decimal("90")


def test_refund_expired_unknown_request_never_gets_new_key(payments, monkeypatch):
    ident = insert_payment(payments, payment_status="PAID", paid_at=now(), paypal_capture_id="capture",
                           refund_status="REQUESTED", refund_requested_amount=100)
    payments["pg"].fail_refund = True
    assert not execute_refund(payments["db"], payments["pg"], ident)
    monkeypatch.setattr("app.refund_recovery.now", lambda: payments["at"] + timedelta(days=45))
    assert not execute_refund(payments["db"], payments["pg"], ident, manual=True)
    assert len(payments["pg"].refunds) == 1
    assert payment_rows(payments)[0]["refund_attempt_state"]["lastError"] == "REFUND_IDEMPOTENCY_WINDOW_EXPIRED"


def test_pg_read_reconciliation_is_distinguished_from_webhook(payments, monkeypatch):
    from app.payment_recovery import reconcile_payments
    insert_payment(payments, paypal_order_id="safe-order", payment_status="PENDING")
    snapshot = {"order": {"id": "safe-order", "purchase_units": [{"payee": {"merchant_id": "SELLER1234567"}}]}, "capture": {"id": "safe-capture", "status": "COMPLETED",
        "create_time": payments["at"].isoformat() + "Z"}, "refunds": {}, "refund": None, "amount": ("USD", Decimal("100"))}
    monkeypatch.setattr(payments["pg"], "snapshot", lambda event: snapshot, raising=False)
    assert reconcile_payments(payments["db"], payments["pg"]) == {"checked": 1, "failed": 0}
    assert payment_rows(payments)[0]["payment_status"] == "PAID"
    with payments["engine"].connect() as conn:
        assert conn.scalar(select(metadata.tables["MSP_PAYPAL_WEBHOOK_EVENT"].c.verification_status)) == "API_QUERY"
    assert reconcile_payments(payments["db"], payments["pg"]) == {"checked": 0, "failed": 0}


def test_out_of_order_capture_waits_for_original_payment_result(payments):
    insert_payment(payments, paypal_order_id="original-order", payment_status="PENDING", capture_requested_at=now())
    insert_payment(payments, paypal_order_id="extra-order")
    with pytest.raises(Problem, match="PAYMENT_PRIOR_ATTEMPT_UNRESOLVED"):
        complete_event(payments, "extra-order", "extra-capture", payments["at"] + timedelta(minutes=1))
    assert all(row["paid_at"] is None for row in payment_rows(payments))
    complete_event(payments, "original-order", "original-capture", payments["at"])
    complete_event(payments, "extra-order", "extra-capture", payments["at"] + timedelta(minutes=1))
    first, second = payment_rows(payments)
    assert first["refund_status"] == "NONE" and second["refund_requested_amount"] == 100


def test_refund_failure_requires_get_confirmation_before_new_key(payments, monkeypatch):
    ident = insert_payment(payments, payment_status="PAID", paid_at=now(), paypal_capture_id="capture",
                           refund_status="REQUESTED", refund_requested_amount=90)
    posts, gets = [], []
    def fail_refund(capture, key, currency, value):
        posts.append(key)
        return {"id": "failed-refund", "status": "FAILED", "amount": {"currency_code": currency, "value": str(value)}}
    def get_refund(kind, refund_id):
        gets.append(refund_id)
        return {"id": refund_id, "status": "FAILED", "amount": {"currency_code": "USD", "value": "90.00"}}
    monkeypatch.setattr(payments["pg"], "refund", fail_refund)
    monkeypatch.setattr(payments["pg"], "get", get_refund)
    assert not execute_refund(payments["db"], payments["pg"], ident)
    monkeypatch.setattr("app.refund_recovery.now", lambda: payments["at"] + timedelta(minutes=10))
    assert not execute_refund(payments["db"], payments["pg"], ident)
    assert len(posts) == 1 and gets == ["failed-refund"]
    monkeypatch.setattr("app.refund_recovery.now", lambda: payments["at"] + timedelta(minutes=20))
    assert not execute_refund(payments["db"], payments["pg"], ident)
    assert len(posts) == 2 and posts[0] != posts[1]


def test_delayed_refund_pending_event_uses_current_pg_completed_status(payments):
    ident = insert_payment(payments, payment_status="PARTIALLY_REFUNDED", paid_at=payments["at"],
                           paypal_capture_id="capture", paypal_order_id="safe-order", refunded_amount=90,
                           refund_status="REQUESTED", refund_requested_amount=100)
    refund = {"id": "old-refund", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "90.00"}}
    event = {"id": "late-refund-event", "event_type": "PAYMENT.REFUND.PENDING", "resource": refund}
    stored = save_event(payments["db"], "SANDBOX", event, json.dumps(event), {})
    snapshot = {"order": {"id": "safe-order", "purchase_units": [{"payee": {"merchant_id": "SELLER1234567"}}]}, "capture": {"id": "capture", "status": "PARTIALLY_REFUNDED",
        "create_time": payments["at"].isoformat() + "Z"}, "refunds": {"old-refund": ("USD", Decimal("90"))},
        "refund": refund, "amount": ("USD", Decimal("100"))}
    process_event(payments["db"], payments["pg"], stored, snapshot)
    row = payment_rows(payments)[0]
    assert row["refund_status"] == "REQUESTED" and row["paypal_refund_id"] is None
    assert execute_refund(payments["db"], payments["pg"], ident)
    assert payments["pg"].refunds[-1][1] == Decimal("10")
