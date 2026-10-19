import base64
import json
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.errors import Problem
from app.paypal import PayPalClient
from app.rental_schema import metadata
from test_admin_customer_inbox import seed
from test_payment_safety import payments, insert_payment, order, capture, payment_rows


PATH = "/nadreego/shop/paypal-merchant"
SELLER = "SELLER1234567"


def test_manual_seller_assignment_is_replaced_by_onboarding(setup, signin):
    metadata.create_all(setup["engine"])
    headers = signin()
    response = setup["client"].put(PATH, headers=headers, json={"spotMasterId": "root", "merchantId": SELLER})
    assert response.status_code == 409 and response.json()["errorCode"] == "PAYPAL_ONBOARDING_REQUIRED"
    assert setup["client"].put(PATH, headers=headers, json={"spotMasterId": "root", "merchantId": None}).status_code == 200
    assert setup["client"].get(PATH, headers=headers, params={"spotMasterId": "root"}).json()["merchantId"] is None


@pytest.mark.parametrize("admin,status", [("general", 403), ("outsider", 404)])
def test_seller_update_permissions(setup, signin, admin, status):
    response = setup["client"].put(PATH, headers=signin(admin), json={"spotMasterId": "root", "merchantId": SELLER})
    assert response.status_code == status, response.text


@pytest.mark.parametrize("value", ["", " bad-id ", "a" * 13, "A" * 14])
def test_invalid_merchant_id_is_rejected(setup, signin, value):
    assert setup["client"].put(PATH, headers=signin(), json={"spotMasterId": "root", "merchantId": value}).status_code == 422


def test_unverified_seller_does_not_overwrite_setting(setup, signin, monkeypatch):
    def reject(value):
        raise Problem(409, "PAYPAL_MERCHANT_NOT_READY")
    monkeypatch.setattr(setup["app"].state.paypal, "verify_merchant", reject)
    headers = signin()
    response = setup["client"].put(PATH, headers=headers, json={"spotMasterId": "root", "merchantId": "OTHER12345678"})
    assert response.status_code == 409
    assert setup["client"].get(PATH, headers=headers, params={"spotMasterId": "root"}).json()["merchantId"] == SELLER


def test_missing_seller_blocks_approval_but_allows_rejection(setup, signin):
    seed(setup)
    table = setup["db"].table("MSP_SPOT_RENT")
    with setup["engine"].begin() as conn:
        conn.execute(table.update().where(table.c.spot_master_id == "root").values(paypal_merchant_id=None))
    headers = signin()
    body = {"bookedNo": "BOinbox-booking", "action": "APPROVE"}
    response = setup["client"].post("/nadreego/booking/action", headers=headers, json=body)
    assert response.status_code == 409 and response.json()["errorCode"] == "SHOP_PAYPAL_MERCHANT_REQUIRED"
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(metadata.tables["MSP_RESERVATION"].c.reservation_status)) == "REQUESTED"
        assert conn.execute(select(metadata.tables["MSP_RESERVATION_HISTORY"])).first() is None
    body["action"] = "REJECT"
    response = setup["client"].post("/nadreego/booking/action", headers=headers, json=body)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("values,code", [({"paypal_merchant_id": None}, "SHOP_PAYPAL_MERCHANT_REQUIRED"),
    ({"paypal_environment": "LIVE"}, "SHOP_PAYPAL_ENVIRONMENT_MISMATCH")])
def test_missing_or_cross_environment_seller_never_creates_order(payments, values, code):
    table = payments["db"].table("MSP_SPOT_RENT")
    with payments["engine"].begin() as conn:
        conn.execute(table.update().where(table.c.spot_master_id == "root").values(**values))
    response = order(payments)
    assert response.status_code == 409 and response.json()["errorCode"] == code
    assert not payment_rows(payments) and not payments["pg"].orders


def test_existing_payment_keeps_original_seller_after_spot_update(payments):
    assert order(payments).status_code == 200
    payment = payment_rows(payments)[0]
    assert payment["paypal_merchant_id"] == SELLER
    table = payments["db"].table("MSP_SPOT_RENT")
    with payments["engine"].begin() as conn:
        conn.execute(table.update().values(paypal_merchant_id="OTHER12345678"))
    assert capture(payments, payment["payment_id"]).status_code == 200
    assert payments["pg"].merchant_id == SELLER


def test_disconnected_spot_blocks_capture_before_provider_call(payments, monkeypatch):
    ident = insert_payment(payments, paypal_order_id="safe-order")
    table = payments["db"].table("MSP_SPOT_RENT")
    with payments["engine"].begin() as conn:
        conn.execute(table.update().values(paypal_merchant_id=None))
    def unexpected(*args):
        pytest.fail("Disconnected spot must not contact PayPal")
    monkeypatch.setattr(payments["pg"], "get", unexpected)
    response = capture(payments, ident)
    assert response.status_code == 409 and response.json()["errorCode"] == "SHOP_PAYPAL_MERCHANT_REQUIRED"
    assert payment_rows(payments)[0]["capture_requested_at"] is None


def test_legacy_payment_without_seller_is_not_inferred(payments):
    ident = insert_payment(payments, paypal_order_id="safe-order", paypal_merchant_id=None)
    response = capture(payments, ident)
    assert response.status_code == 409
    assert response.json()["errorCode"] == "PAYMENT_MERCHANT_RECONCILIATION_REQUIRED"
    assert not payments["pg"].captures


def test_wrong_payee_blocks_capture(payments, monkeypatch):
    ident = insert_payment(payments, paypal_order_id="safe-order")
    monkeypatch.setattr(payments["pg"], "get", lambda *args: {"id": "safe-order", "status": "APPROVED",
        "purchase_units": [{"payee": {"merchant_id": "OTHER12345678"}}]})
    response = capture(payments, ident)
    assert response.status_code == 409 and response.json()["errorCode"] == "PAYPAL_MERCHANT_MISMATCH"
    assert not payments["pg"].captures


def test_refund_retains_seller_after_spot_is_disconnected(payments):
    from app.refund_recovery import execute_refund
    ident = insert_payment(payments, payment_status="PAID", paypal_capture_id="capture",
        refund_status="REQUESTED", refund_requested_amount=90)
    table = payments["db"].table("MSP_SPOT_RENT")
    with payments["engine"].begin() as conn:
        conn.execute(table.update().values(paypal_merchant_id=None, paypal_environment=None))
    assert execute_refund(payments["db"], payments["pg"], ident)
    assert payments["pg"].merchant_id == SELLER


def test_webhook_cannot_apply_another_seller_snapshot(payments):
    from app.paypal import process_event, save_event
    insert_payment(payments, paypal_order_id="safe-order")
    event = {"id": "wrong-seller-event", "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "safe-order"}}
    stored = save_event(payments["db"], "SANDBOX", event, json.dumps(event), {})
    snapshot = {"order": {"id": "safe-order", "purchase_units": [{"payee": {"merchant_id": "OTHER12345678"}}]}, "capture": None}
    with pytest.raises(Problem, match="PAYPAL_MERCHANT_MISMATCH"):
        process_event(payments["db"], payments["pg"], stored, snapshot)
    assert payment_rows(payments)[0]["payment_status"] == "CREATED"


def test_missing_merchant_columns_are_planned_without_backfill(setup, monkeypatch):
    from sqlalchemy import inspect
    from app.migrate import migration_plan
    metadata.create_all(setup["engine"])
    inspector = inspect(setup["engine"])
    original = inspector.get_columns
    missing = {"MSP_SPOT_RENT": {"paypal_merchant_id", "paypal_environment"},
               "MSP_RENTAL_PAYMENT": {"paypal_merchant_id"}}
    monkeypatch.setattr(inspector, "get_columns", lambda name, **kwargs: [
        column for column in original(name, **kwargs) if column["name"] not in missing.get(name, set())])
    monkeypatch.setattr("app.migrate.inspect", lambda engine: inspector)
    plan = migration_plan(setup["db"])
    changes = [(label, sql) for label, sql, params in plan if "paypal_merchant_id" in label or "paypal_environment" in label]
    assert len(changes) == 3
    assert all("DEFAULT NULL" in sql and "UNIQUE" not in sql and "UPDATE " not in sql for label, sql in changes)


def test_platform_request_has_seller_payee_and_auth_assertion():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(201, json={"id": "ORDER-1"})
    settings = Settings(_env_file=None, paypal_client_id="platform-client", paypal_client_secret="secret", paypal_webhook_id="wh")
    client = PayPalClient(settings, httpx.MockTransport(handler))
    try:
        client.for_merchant(SELLER).create_order("request-1", "USD", Decimal("10.00"), "booking")
        assert client.merchant_id is None
        request = requests[-1]
        assert json.loads(request.content)["purchase_units"][0]["payee"]["merchant_id"] == SELLER
        parts = request.headers["PayPal-Auth-Assertion"].split(".")
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        assert payload == {"iss": "platform-client", "payer_id": SELLER}
        assert parts[2] == ""
        with pytest.raises(Problem):
            client.create_order("request-2", "USD", Decimal("10.00"), "booking")
    finally:
        client.close()


@pytest.mark.parametrize("ready,partner", [(True, "platform-client"), (False, "platform-client"), (True, "wrong-app")])
def test_merchant_verification_requires_current_platform_consent(ready, partner):
    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(200, json={"merchant_id": SELLER, "payments_receivable": ready,
            "primary_email_confirmed": True, "oauth_integrations": [{"integration_type": "OAUTH_THIRD_PARTY",
                "oauth_third_party": [{"partner_client_id": partner, "scopes": [
                    "https://uri.paypal.com/services/payments/realtimepayment", "https://uri.paypal.com/services/payments/refund"]}]}]})
    client = PayPalClient(Settings(_env_file=None, paypal_client_id="platform-client", paypal_client_secret="secret",
        paypal_webhook_id="wh", paypal_partner_merchant_id="PARTNER123456"), httpx.MockTransport(handler))
    try:
        if ready and partner == "platform-client":
            client.verify_merchant(SELLER)
        else:
            with pytest.raises(Problem, match="PAYPAL_MERCHANT_NOT_READY"):
                client.verify_merchant(SELLER)
    finally:
        client.close()
