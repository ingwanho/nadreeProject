import logging

import httpx
import pytest

from app.config import Settings
from app.errors import Problem
from app.paypal import PayPalClient


@pytest.mark.parametrize("failure", ["oauth", "capture", "transport", "malformed"])
def test_provider_diagnostics_exclude_sensitive_data(caplog, failure):
    secret = "private-secret-never-log"
    token = "private-access-token-never-log"
    def handler(request):
        if failure == "transport":
            raise httpx.ConnectError("private exception " + secret, request=request)
        if request.url.path == "/v1/oauth2/token":
            if failure == "oauth":
                return httpx.Response(401, headers={"paypal-debug-id": "debug-oauth"},
                    json={"error": "invalid_client", "error_description": secret})
            return httpx.Response(200, json={"access_token": token, "expires_in": 3600})
        if failure == "malformed":
            return httpx.Response(200, headers={"paypal-debug-id": "debug-malformed"}, text=secret)
        return httpx.Response(422, headers={"paypal-debug-id": "debug-capture"},
            json={"name": "UNPROCESSABLE_ENTITY", "message": secret,
                  "details": [{"description": token}]})
    client = PayPalClient(Settings(_env_file=None, paypal_client_id="private-client-id-never-log",
        paypal_client_secret=secret, paypal_webhook_id="private-webhook-never-log"), httpx.MockTransport(handler))
    caplog.set_level(logging.WARNING, logger="app.paypal")
    try:
        with pytest.raises(Problem) as exc:
            client.for_merchant("SELLER1234567").capture_order("private-order-never-log", "request")
        assert exc.value.code == "PAYPAL_SERVICE_UNAVAILABLE"
        records = [r for r in caplog.records if r.name == "app.paypal"]
        assert len(records) == 1 and records[0].exc_info is None
        message = records[0].getMessage()
        assert "http_status=" in message and "error_code=" in message and "paypal_debug_id=" in message
        for value in (secret, token, "private-client-id-never-log", "private-order-never-log", "Authorization", "Bearer", "PayPal-Auth-Assertion"):
            assert value not in message
        if failure == "oauth":
            assert "http_status=401" in message and "invalid_client" in message and "debug-oauth" in message
        elif failure == "capture":
            assert "http_status=422" in message and "UNPROCESSABLE_ENTITY" in message and "debug-capture" in message
        elif failure == "transport":
            assert "http_status=None" in message and "PAYPAL_TRANSPORT_ERROR" in message
        else:
            assert "http_status=200" in message and "PAYPAL_RESPONSE_INVALID" in message
    finally:
        client.close()
