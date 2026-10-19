import pytest
from sqlalchemy import select

from app.pricing import daily_price
from app.rental_schema import metadata

PATH = "/nadreego/shop/tierCreate"


@pytest.fixture
def pricing(setup, signin):
    metadata.create_all(setup["engine"])
    with setup["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RENTAL_TIER"].insert(), [
            dict(spot_master_id=None, tier_type="BASE", min_cc=1, max_cc=50, price=10),
            dict(spot_master_id=None, tier_type="BASE", min_cc=51, max_cc=125, price=20)])
    return setup, signin()


def tier(low, high, price=12):
    return dict(minCc=low, maxCc=high, price=price, type="BASIC", spotCode="root")


def test_partial_override_and_batch_upsert(pricing):
    ctx, headers = pricing
    client = ctx["client"]
    initial = client.get(PATH, headers=headers, params={"spotCode": "root"}).json()
    assert initial["tiers"] == initial["effectiveTiers"]
    response = client.post(PATH, headers=headers, json=[tier(1, 25)])
    assert response.status_code == 200, response.text
    effective = client.get(PATH, headers=headers, params={"spotCode": "root"}).json()["effectiveTiers"]
    assert [(r["minCc"], r["maxCc"], r["price"], r["type"]) for r in effective] == [
        (1, 25, 12, "BASIC"), (26, 50, 10, "BASE"), (51, 125, 20, "BASE")]
    response = client.post(PATH, headers=headers, json=[tier(1, 25, 13), tier(26, 50, 15)])
    assert response.status_code == 200, response.text
    assert [t["action"] for t in response.json()["tiers"]] == ["UPDATED", "CREATED"]
    with ctx["engine"].connect() as conn:
        tiers = list(conn.execute(select(metadata.tables["MSP_RENTAL_TIER"])).mappings())
    for cc, expected in [(1, 13), (25, 13), (26, 15), (50, 15), (51, 20), (125, 20)]:
        assert daily_price({"rental": {"price_type": "BASIC", "premium_daily_price": None},
                            "model": {"cc": cc}}, tiers) == expected
    assert daily_price({"rental": {"price_type": "PREMIUM", "premium_daily_price": 77},
                        "model": {"cc": 1}}, tiers) == 77
    assert all(t["type"] == "BASE" for t in client.get(PATH, headers=headers).json()["effectiveTiers"])


@pytest.mark.parametrize("body,status", [
    ([], 422), ([tier(1, 25), tier(1, 25)], 422),
    ([tier(1, 25), tier(20, 50)], 409), ([tier(1, 25), tier(40, 60)], 409),
    ([tier(1, 25), tier(26, 50, 1.5)], 422),
    ([tier(1, 25), {**tier(26, 50), "spotCode": "child"}], 422)])
def test_invalid_batch_is_atomic(pricing, body, status):
    ctx, headers = pricing
    response = ctx["client"].post(PATH, headers=headers, json=body)
    assert response.status_code == status, response.text
    with ctx["engine"].connect() as conn:
        assert len(conn.execute(select(metadata.tables["MSP_RENTAL_TIER"])).all()) == 2


def test_single_compatibility_and_rollback_update(pricing):
    ctx, headers = pricing
    response = ctx["client"].post(PATH, headers=headers, json=tier(1, 25))
    assert response.status_code == 200 and response.json()["tier"]["action"] == "CREATED"
    response = ctx["client"].post(PATH, headers=headers, json=[tier(1, 25, 99), tier(20, 50)])
    assert response.status_code == 409
    data = ctx["client"].get(PATH, headers=headers, params={"spotCode": "root"}).json()
    assert next(t for t in data["tiers"] if t["type"] == "BASIC")["price"] == 12


def test_same_total_options_require_explicit_grade(monkeypatch):
    from types import SimpleNamespace
    from copy import deepcopy
    from app.customer_rentals import _quote_for_request
    from app.errors import Problem
    tiers = [{"priceType": kind, "priceOptionId": kind + ":10", "dailyPriceFrom": 10, "totalPrice": 20}
             for kind in ("BASIC", "PREMIUM")]
    item = {"canRequest": True, "price": {"totalOptions": [20], "totalFrom": 20, "totalTo": 20,
                                          "pricingTiers": tiers, "rentalDays": 2}}
    monkeypatch.setattr("app.customer_rentals._availability_for", lambda *args, **kwargs: [deepcopy(item)])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(rental_currency="USD"))))
    body = SimpleNamespace(currency="USD", spotMasterId="root", modelId="model", totalPrice=20, priceOptionId=None)
    with pytest.raises(Problem) as error:
        _quote_for_request(request, None, body)
    assert error.value.code == "PRICE_OPTION_REQUIRED"
    body.priceOptionId = "PREMIUM:10"
    quote = _quote_for_request(request, None, body)
    assert quote["price"]["pricingTiers"][0]["priceType"] == "PREMIUM"
    body.priceOptionId = "PREMIUM:11"
    with pytest.raises(Problem) as error:
        _quote_for_request(request, None, body)
    assert error.value.code == "PRICE_OPTION_INVALID"
