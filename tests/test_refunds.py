import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.paypal import PayPalClient
from app.security import decode_user_access, sign_user_access
from app.rental_inputs import NadriAvailability, NadriProfile, NadriRentalRequest


def paypal_settings():
    return Settings(_env_file=None, env="test", jwt_secret="isolated-test-key-not-for-deployment-123456789",
                    paypal_client_id="client", paypal_client_secret="secret",
                    paypal_webhook_id="webhook", paypal_merchant_id="merchant")


def test_paypal_refund_uses_capture_endpoint_and_idempotency_header():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(201, json={"id": "refund-1", "status": "PENDING"})

    client = PayPalClient(paypal_settings(), transport=httpx.MockTransport(handler))
    try:
        result = client.refund("capture-1", "nadree-refund-1", "USD", Decimal("12.34"))
    finally:
        client.close()
    assert result == {"id": "refund-1", "status": "PENDING"}
    request = requests[-1]
    assert request.method == "POST"
    assert request.url.path == "/v2/payments/captures/capture-1/refund"
    assert request.headers["PayPal-Request-Id"] == "nadree-refund-1"
    assert request.headers["Prefer"] == "return=representation"
    assert json.loads(request.content) == {"amount": {"currency_code": "USD", "value": "12.34"}}


def test_nadri_user_access_token_is_separate_from_admin_audience():
    settings = paypal_settings()
    token = sign_user_access(settings, "uid-1")
    claims = decode_user_access(settings, token)
    assert claims["sub"] == "uid-1"
    assert claims["type"] == "nadri_user_access"
    assert claims["exp"] - claims["iat"] == 3600


def test_nadri_profile_uses_gender_and_nationality_codes():
    profile = NadriProfile(GENDER="OTHER", NATIONALITY="KR")
    assert profile.GENDER == "OTHER" and profile.NATIONALITY == "KR"
    with pytest.raises(ValidationError):
        NadriProfile(GENDER="X")
    with pytest.raises(ValidationError):
        NadriProfile(NATIONALITY="kr")


def test_nadri_delivery_return_location_is_optional():
    availability = NadriAvailability(startDate=date(2026, 10, 1), returnDate=date(2026, 10, 4), cc=125,
                                      deliveryRequested=True, pickupLocation="Jl. Raya Kuta No. 10")
    assert availability.returnLocation is None

    request = NadriRentalRequest(spotMasterId="spot-1", modelId="model-1", startDate=date(2026, 10, 1),
                                 returnDate=date(2026, 10, 4), totalPrice=100, currency="USD",
                                 deliveryRequested=True, pickupLocation="Jl. Raya Kuta No. 10")
    assert request.returnLocation is None

    with pytest.raises(ValidationError, match="pickup location required"):
        NadriAvailability(startDate=date(2026, 10, 1), returnDate=date(2026, 10, 4), cc=125,
                           deliveryRequested=True)
