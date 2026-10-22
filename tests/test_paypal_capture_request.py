import json

import httpx
import pytest

from app.config import Settings
from app.paypal import PayPalClient
from test_payment_safety import payments, insert_payment, payment_rows, capture


def provider_settings(environment="SANDBOX"):
    return Settings(_env_file=None, paypal_environment=environment,
                    paypal_client_id="isolated-client", paypal_client_secret="isolated-secret",
                    paypal_webhook_id="isolated-webhook", paypal_partner_merchant_id="PLATFM1234567")


@pytest.mark.parametrize("environment,host", [
    ("SANDBOX", "api-m.sandbox.paypal.com"), ("LIVE", "api-m.paypal.com"),
])
def test_capture_sends_json_and_preserves_seller_and_request_identity(environment, host):
    captures = []
    def provider(request):
        assert request.url.host == host
        if request.url.path == "/v1/oauth2/token":
            assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
            assert request.content == b"grant_type=client_credentials"
            return httpx.Response(200, json={"access_token": "isolated-token", "expires_in": 3600})
        assert request.method == "POST" and request.url.path == "/v2/checkout/orders/test-order/capture"
        if request.headers.get("content-type") != "application/json":
            return httpx.Response(415, json={"name": "UNSUPPORTED_MEDIA_TYPE"})
        assert json.loads(request.content) == {}
        assert request.headers["paypal-request-id"] == "nadree-capture-7"
        assert request.headers["prefer"] == "return=representation"
        assert request.headers["authorization"] == "Bearer isolated-token"
        assert request.headers.get("paypal-auth-assertion")
        captures.append(request.headers["paypal-request-id"])
        return httpx.Response(201, json={"id": "test-order", "status": "COMPLETED"})
    client = PayPalClient(provider_settings(environment), httpx.MockTransport(provider))
    try:
        seller = client.for_merchant("SELLER1234567")
        for _ in range(2):
            assert seller.capture_order("test-order", "nadree-capture-7")["status"] == "COMPLETED"
        assert captures == ["nadree-capture-7", "nadree-capture-7"]
    finally:
        client.close()


def test_capture_api_uses_json_and_waits_for_settlement_without_second_capture(payments):
    ident = insert_payment(payments, paypal_order_id="test-order")
    capture_requests = []
    def provider(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "isolated-token", "expires_in": 3600})
        if request.method == "GET" and request.url.path == "/v2/checkout/orders/test-order":
            return httpx.Response(200, json={"id": "test-order", "status": "APPROVED",
                "purchase_units": [{"payee": {"merchant_id": "SELLER1234567"},
                                    "amount": {"currency_code": "USD", "value": "100.00"}}]})
        if request.method == "GET" and request.url.path.endswith("/merchant-integrations/SELLER1234567"):
            assert "paypal-auth-assertion" not in request.headers
            return httpx.Response(200, json={"merchant_id": "SELLER1234567", "payments_receivable": True,
                "primary_email_confirmed": True, "oauth_integrations": [{"integration_type": "OAUTH_THIRD_PARTY",
                    "oauth_third_party": [{"partner_client_id": "isolated-client", "scopes": [
                        "https://uri.paypal.com/services/payments/realtimepayment",
                        "https://uri.paypal.com/services/payments/refund"]}]}]})
        assert request.method == "POST" and request.url.path == "/v2/checkout/orders/test-order/capture"
        if request.headers.get("content-type") != "application/json":
            return httpx.Response(415, json={"name": "UNSUPPORTED_MEDIA_TYPE"})
        assert json.loads(request.content) == {}
        assert request.headers["paypal-request-id"] == "nadree-capture-" + str(ident)
        assert request.headers.get("paypal-auth-assertion")
        capture_requests.append(request.headers["paypal-request-id"])
        return httpx.Response(201, json={"id": "test-order", "status": "COMPLETED", "purchase_units": [
            {"payments": {"captures": [{"id": "test-capture", "status": "COMPLETED"}]}}]})
    provider_client = PayPalClient(provider_settings(), httpx.MockTransport(provider))
    payments["app"].state.paypal = provider_client
    try:
        response = capture(payments, ident)
        assert response.status_code == 200, response.text
        assert response.json()["paypalCaptureId"] == "test-capture"
        assert response.json()["paymentStatus"] == "PENDING"
        assert response.json()["nextAction"] == "WAIT"
        row = dict(payment_rows(payments)[0])
        assert row["capture_requested_at"] is not None and row["paid_at"] is None
        assert row["paypal_capture_id"] == "test-capture"
        assert capture(payments, ident).status_code == 200
        assert dict(payment_rows(payments)[0])["capture_requested_at"] == row["capture_requested_at"]
        assert capture_requests == ["nadree-capture-" + str(ident)]
        assert len(payment_rows(payments)) == 1
    finally:
        provider_client.close()
