from decimal import Decimal

import httpx
import pytest

from app.config import Settings
from app.errors import Problem
from app.paypal import PayPalClient


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
