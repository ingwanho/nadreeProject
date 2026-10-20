from datetime import timedelta

import pytest

from app.errors import Problem
from app.paypal import PayPalClient
from app.security import now
from test_payment_safety import payments, insert_payment, payment_rows, order, capture


def status(ctx, ident):
    return ctx["client"].get("/api/v1/nadree/rental/payment/" + str(ident), headers=ctx["headers"])


def real_links(ctx, monkeypatch):
    pg = ctx["pg"]
    get = pg.get
    def provider_get(resource, ident):
        result = get(resource, ident)
        if result["status"] in ("CREATED", "SAVED", "PAYER_ACTION_REQUIRED"):
            result["links"] = [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=test"}]
        return result
    monkeypatch.setattr(pg, "get", provider_get)
    monkeypatch.setattr(pg, "approval_url", lambda result: PayPalClient.approval_url(pg, result))


@pytest.mark.parametrize("provider_status,action", [
    ("CREATED", "APPROVE"), ("SAVED", "APPROVE"),
    ("PAYER_ACTION_REQUIRED", "APPROVE"), ("APPROVED", "CAPTURE"),
])
def test_order_and_status_expose_verified_payment_step(payments, monkeypatch, provider_status, action):
    real_links(payments, monkeypatch)
    payments["pg"].order_status = provider_status
    ident = insert_payment(payments, paypal_order_id="safe-order")
    for response in (order(payments), status(payments, ident)):
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["paypalOrderStatus"] == provider_status
        assert data["nextAction"] == action
        assert data["canCapture"] == (action == "CAPTURE")
        assert bool(data["approvalUrl"]) == (action == "APPROVE")
        assert data["paymentStatus"] == "CREATED"
    assert not payments["pg"].orders and not payments["pg"].captures


def test_early_capture_does_not_leave_pending_checkpoint(payments, monkeypatch):
    real_links(payments, monkeypatch)
    ident = insert_payment(payments, paypal_order_id="safe-order")
    payments["pg"].order_status = "CREATED"
    response = capture(payments, ident)
    assert response.status_code == 409 and response.json()["errorCode"] == "PAYMENT_STATE_INVALID"
    row = payment_rows(payments)[0]
    assert row["payment_status"] == "CREATED" and row["capture_requested_at"] is None
    assert order(payments).json()["nextAction"] == "APPROVE"
    assert not payments["pg"].captures


def test_failed_seller_preflight_does_not_record_capture(payments, monkeypatch):
    ident = insert_payment(payments, paypal_order_id="safe-order")
    def fail(merchant):
        raise Problem(500, "PAYPAL_SERVICE_UNAVAILABLE")
    monkeypatch.setattr(payments["pg"], "verify_merchant", fail)
    assert capture(payments, ident).status_code == 500
    row = payment_rows(payments)[0]
    assert row["payment_status"] == "CREATED" and row["capture_requested_at"] is None
    assert not payments["pg"].captures


def test_capture_timeout_can_retry_same_payment_after_provider_read(payments):
    ident = insert_payment(payments, paypal_order_id="safe-order")
    payments["pg"].fail_capture = True
    assert capture(payments, ident).status_code == 503
    checkpoint = payment_rows(payments)[0]["capture_requested_at"]
    response = status(payments, ident)
    assert response.status_code == 200
    assert response.json()["nextAction"] == "RETRY_CAPTURE"
    assert response.json()["canCapture"] is True
    assert response.json()["paypalOrderStatus"] == "APPROVED"
    assert len(payments["pg"].captures) == 1  # GET did not retry capture.
    payments["pg"].fail_capture = False
    assert capture(payments, ident).status_code == 200
    assert payments["pg"].captures == ["nadree-capture-" + str(ident)] * 2
    rows = payment_rows(payments)
    assert len(rows) == 1 and rows[0]["capture_requested_at"] == checkpoint
    assert not payments["pg"].orders


def test_retry_window_expiry_requires_review(payments):
    ident = insert_payment(payments, paypal_order_id="safe-order", payment_status="PENDING",
                           capture_requested_at=now() - timedelta(hours=6))
    data = status(payments, ident).json()
    assert data["paypalOrderStatus"] == "APPROVED"
    assert data["nextAction"] == "REVIEW" and data["canCapture"] is False
    response = capture(payments, ident)
    assert response.status_code == 409 and response.json()["errorCode"] == "PAYMENT_RECONCILIATION_REQUIRED"
    assert not payments["pg"].captures and not payments["pg"].orders


@pytest.mark.parametrize("code,action", [("PAYPAL_SERVICE_UNAVAILABLE", "WAIT"),
                                        ("PAYPAL_MERCHANT_MISMATCH", "REVIEW")])
def test_failed_order_read_never_grants_capture(payments, monkeypatch, code, action):
    ident = insert_payment(payments, paypal_order_id="safe-order", payment_status="PENDING", capture_requested_at=now())
    def fail(*args):
        raise Problem(500, code)
    monkeypatch.setattr(payments["pg"], "get", fail)
    response = status(payments, ident)
    assert response.status_code == 200
    assert response.json()["paypalOrderStatus"] is None
    assert response.json()["nextAction"] == action and response.json()["canCapture"] is False
    assert payment_rows(payments)[0]["payment_status"] == "PENDING"
    assert not payments["pg"].captures


def test_provider_capture_blocks_another_attempt_until_reconciled(payments, monkeypatch):
    ident = insert_payment(payments, paypal_order_id="safe-order", payment_status="PENDING", capture_requested_at=now())
    get = payments["pg"].get
    def completed(resource, value):
        result = get(resource, value)
        result["status"] = "COMPLETED"
        result["purchase_units"][0]["payments"] = {"captures": [{"id": "already-captured", "status": "COMPLETED"}]}
        return result
    monkeypatch.setattr(payments["pg"], "get", completed)
    assert status(payments, ident).json()["nextAction"] == "WAIT"
    assert capture(payments, ident).status_code == 409
    assert not payments["pg"].captures


def test_settled_payment_is_done_without_provider_request(payments, monkeypatch):
    ident = insert_payment(payments, payment_status="PAID", paypal_order_id="safe-order", paypal_capture_id="capture")
    def unexpected(*args):
        pytest.fail("Settled payment must not re-open provider authorization")
    monkeypatch.setattr(payments["pg"], "get", unexpected)
    data = status(payments, ident).json()
    assert data["nextAction"] == "DONE" and data["canCapture"] is False


def test_pending_capture_id_is_wait_not_retry(payments):
    ident = insert_payment(payments, payment_status="PENDING", paypal_order_id="safe-order", paypal_capture_id="capture")
    data = status(payments, ident).json()
    assert data["nextAction"] == "WAIT" and data["canCapture"] is False
