from datetime import timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from sqlalchemy import select

from app.errors import Problem
from app.rental_schema import metadata
from app.security import now

BASE = "/nadreego/shop/paypal-onboarding"


@pytest.fixture
def onboarding(setup, signin, monkeypatch):
    metadata.create_all(setup["engine"])
    setup["settings"].paypal_onboarding_return_url = "https://example.com/paypal-return"
    table = setup["db"].table("MSP_SPOT_RENT")
    with setup["engine"].begin() as conn:
        conn.execute(table.update().where(table.c.spot_master_id == "root").values(paypal_merchant_id=None, paypal_environment=None))
    calls = []
    def url(sid, callback, path=None):
        calls.append((sid, callback, path))
        return "https://www.sandbox.paypal.com/onboarding", "/v2/customer/partner-referrals/test"
    monkeypatch.setattr(setup["app"].state.paypal, "onboarding_url", url)
    monkeypatch.setattr(setup["app"].state.paypal, "seller_by_tracking", lambda sid: "SELLER1234567")
    return setup, signin(), calls


def test_start_verify_existing_columns_and_disconnect(onboarding):
    ctx, headers, calls = onboarding
    client = ctx["client"]
    body = {"spotMasterId": "root"}
    first = client.post(BASE + "/start", headers=headers, json=body)
    assert first.status_code == 200, first.text
    payload = {**body, "state": first.json()["state"]}
    assert parse_qs(urlsplit(calls[0][1]).query)["state"] == [payload["state"]]
    assert client.post(BASE + "/verify", headers=headers, json={**payload, "merchantId": "OTHER12345678"}).status_code == 422
    for _ in range(2):
        result = client.post(BASE + "/verify", headers=headers, json=payload)
        assert result.status_code == 200 and result.json()["merchantId"] == "SELLER1234567"
    assert client.post(BASE + "/start", headers=headers, json=body).status_code == 409
    state = client.get("/nadreego/shop/paypal-merchant", headers=headers, params=body)
    assert state.json()["merchantId"] == "SELLER1234567"
    # The child already uses the same seller: no cross-spot uniqueness restriction.
    with ctx["engine"].connect() as conn:
        table = ctx["db"].table("MSP_SPOT_RENT")
        assert conn.scalar(select(table.c.paypal_merchant_id).where(table.c.spot_master_id == "child")) == "SELLER1234567"
    assert client.put("/nadreego/shop/paypal-merchant", headers=headers, json={**body, "merchantId": None}).status_code == 200
    assert client.get("/nadreego/shop/paypal-merchant", headers=headers, params=body).json()["merchantId"] is None


def test_only_direct_primary_can_onboard(onboarding, signin):
    ctx, headers, calls = onboarding
    assert ctx["client"].post(BASE + "/start", headers=signin("general"), json={"spotMasterId": "root"}).status_code == 403
    assert ctx["client"].post(BASE + "/start", headers=headers, json={"spotMasterId": "child"}).status_code == 403
    assert not calls


def test_failed_verification_does_not_store_seller(onboarding, monkeypatch):
    ctx, headers, _ = onboarding
    first = ctx["client"].post(BASE + "/start", headers=headers, json={"spotMasterId": "root"}).json()
    def incomplete(sid):
        raise Problem(409, "PAYPAL_ONBOARDING_INCOMPLETE")
    monkeypatch.setattr(ctx["app"].state.paypal, "seller_by_tracking", incomplete)
    assert ctx["client"].post(BASE + "/verify", headers=headers,
        json={"spotMasterId": "root", "state": first["state"]}).status_code == 409
    with ctx["engine"].connect() as conn:
        table = ctx["db"].table("MSP_SPOT_RENT")
        assert conn.scalar(select(table.c.paypal_merchant_id).where(table.c.spot_master_id == "root")) is None


@pytest.mark.parametrize("change,status", [("tampered", 400), ("expired", 410), ("spot", 400), ("env", 400), ("sid", 400)])
def test_invalid_state_never_queries_paypal(onboarding, monkeypatch, change, status):
    ctx, headers, _ = onboarding
    token = ctx["client"].post(BASE + "/start", headers=headers, json={"spotMasterId": "root"}).json()["state"]
    claims = jwt.decode(token, options={"verify_signature": False})
    if change == "expired":
        claims["exp"] = int((now().replace(tzinfo=timezone.utc) - timedelta(seconds=1)).timestamp())
    elif change != "tampered":
        claims[change] = "wrong"
    token = jwt.encode(claims, "wrong-secret-at-least-thirty-two-bytes" if change == "tampered" else
        ctx["settings"].jwt_secret.get_secret_value(), algorithm="HS256")
    def unexpected(sid):
        pytest.fail("Invalid state must not query PayPal")
    monkeypatch.setattr(ctx["app"].state.paypal, "seller_by_tracking", unexpected)
    result = ctx["client"].post(BASE + "/verify", headers=headers, json={"spotMasterId": "root", "state": token})
    assert result.status_code == status, result.text


def test_provider_contract_uses_tracking_and_trusted_paypal_urls(monkeypatch):
    import httpx
    import json
    from app.config import Settings
    from app.paypal import PayPalClient
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "test", "expires_in": 3600})
        if request.url.path == "/v2/customer/partner-referrals":
            body = json.loads(request.content)
            assert body["tracking_id"] == "tracking-123"
            assert body["operations"][0]["api_integration_preference"]["rest_api_integration"]["third_party_details"]["features"] == ["PAYMENT", "REFUND"]
            return httpx.Response(201, json={"links": [
                {"rel": "action_url", "href": "https://www.sandbox.paypal.com/onboarding"},
                {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/customer/partner-referrals/test"}]})
        assert request.url.params["tracking_id"] == "tracking-123"
        return httpx.Response(200, json={"tracking_id": "tracking-123", "merchant_id": "SELLER1234567"})
    client = PayPalClient(Settings(_env_file=None, paypal_client_id="test", paypal_client_secret="test",
                                   paypal_webhook_id="test", paypal_partner_merchant_id="PARTNER123456"),
                          transport=httpx.MockTransport(handler))
    validated = []
    monkeypatch.setattr(client, "verify_merchant", validated.append)
    try:
        url, path = client.onboarding_url("tracking-123", "https://example.com/return")
        assert url == "https://www.sandbox.paypal.com/onboarding"
        assert path == "/v2/customer/partner-referrals/test"
        assert client.seller_by_tracking("tracking-123") == "SELLER1234567"
        assert validated == ["SELLER1234567"]
    finally:
        client.close()


@pytest.mark.parametrize("ready", [True, False])
def test_merchant_webhook_rechecks_current_rights_and_updates_only_linked_spots(onboarding, monkeypatch, ready):
    from app.paypal_onboarding import process_merchant_event
    ctx, _, _ = onboarding
    table = metadata.tables["MSP_PAYPAL_WEBHOOK_EVENT"]
    with ctx["engine"].begin() as conn:
        result = conn.execute(table.insert().values(paypal_event_id="merchant-test", payment_environment="SANDBOX",
            event_type="MERCHANT.PARTNER-CONSENT.REVOKED", raw_body="{}", verification_headers={},
            verification_status="VERIFIED", processing_status="PENDING", received_at=now(), updated_at=now()))
        event_id = result.inserted_primary_key[0]
    def verify(seller):
        assert seller == "SELLER1234567"
        if not ready:
            raise Problem(409, "PAYPAL_MERCHANT_NOT_READY")
    monkeypatch.setattr(ctx["app"].state.paypal, "verify_merchant", verify)
    process_merchant_event(ctx["db"], ctx["app"].state.paypal, {"webhook_event_id": event_id},
        {"resource": {"merchant_id": "SELLER1234567"}})
    with ctx["engine"].connect() as conn:
        spots = ctx["db"].table("MSP_SPOT_RENT")
        assert conn.scalar(select(spots.c.paypal_merchant_id).where(spots.c.spot_master_id == "root")) is None
        assert conn.scalar(select(spots.c.paypal_merchant_id).where(spots.c.spot_master_id == "child")) == (
            "SELLER1234567" if ready else None)
        assert conn.scalar(select(table.c.processing_status).where(table.c.webhook_event_id == event_id)) == "PROCESSED"
