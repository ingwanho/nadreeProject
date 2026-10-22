from decimal import Decimal

import httpx
import pytest

from app.config import Settings
from app.errors import Problem
from app.paypal import PayPalClient
from test_payment_safety import payments, insert_payment, payment_rows


@pytest.mark.parametrize("callback", ["", "http://na-dree.com/payment/return",
    "https://user:password@na-dree.com/payment/return", "https://na-dree.com/return?next=other",
    "https://na-dree.com/return#fragment", "https://na-dree.com/return path"])
def test_invalid_payment_return_url_never_calls_paypal(callback):
    def unexpected(request):
        pytest.fail("Invalid callback must not reach PayPal")
    client = PayPalClient(Settings(_env_file=None, paypal_payment_return_url=callback),
                          transport=httpx.MockTransport(unexpected))
    try:
        with pytest.raises(Problem) as error:
            client.for_merchant("SELLER1234567").create_order("request", "USD", Decimal("10.00"), "booking")
        assert error.value.status == 503
        assert error.value.code == "PAYPAL_PAYMENT_RETURN_URL_REQUIRED"
    finally:
        client.close()


@pytest.mark.parametrize("relation", ["approve", "payer-action"])
def test_payment_approval_url_supports_both_paypal_link_relations(relation):
    client = PayPalClient(Settings(_env_file=None))
    url = "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1"
    try:
        assert client.approval_url({"links": [{"rel": relation, "href": url}]}) == url
        with pytest.raises(Problem):
            client.approval_url({"links": [{"rel": relation, "href": "https://example.com/checkoutnow"}]})
    finally:
        client.close()


@pytest.mark.parametrize("query", [
    "",
    "?token=private-order-do-not-echo&PayerID=private-buyer-do-not-echo",
    "?cancelled=true&token=private-order-do-not-echo",
    "?paymentId=7&paymentStatus=PAID&cancelled=untrusted-value",
])
def test_payment_return_is_public_navigation_without_payment_side_effects(payments, monkeypatch, query):
    insert_payment(payments, paypal_order_id="private-order-do-not-echo")
    before = [dict(row) for row in payment_rows(payments)]
    def unexpected(*args, **kwargs):
        pytest.fail("A browser return must not contact PayPal")
    for name in ("get", "create_order", "capture_order"):
        monkeypatch.setattr(payments["pg"], name, unexpected)
    response = payments["client"].get("/api/v1/nadree/rental/payment/return" + query)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "앱에서 결제 상태를 확인해 주세요" in response.text
    for value in ("private-order-do-not-echo", "private-buyer-do-not-echo", "paymentStatus", "PAID"):
        assert value not in response.text
    assert [dict(row) for row in payment_rows(payments)] == before


def test_payment_return_does_not_require_database(payments, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("A browser return must not query the database")
    monkeypatch.setattr(payments["db"], "table", unexpected)
    response = payments["client"].get("/api/v1/nadree/rental/payment/return?token=test")
    assert response.status_code == 200


def test_fixed_return_route_preserves_numeric_payment_status_and_auth(payments):
    ident = insert_payment(payments, paypal_order_id="test-order")
    path = "/api/v1/nadree/rental/payment/" + str(ident)
    assert payments["client"].get(path).status_code == 401
    response = payments["client"].get(path, headers=payments["headers"])
    assert response.status_code == 200
    assert response.json()["paymentId"] == ident
    assert response.json()["nextAction"] == "CAPTURE"
