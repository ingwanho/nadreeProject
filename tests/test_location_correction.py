from datetime import timedelta

import pytest
from sqlalchemy import select

from app.rental_schema import metadata
from app.security import now


@pytest.fixture
def correction(setup):
    metadata.create_all(setup["engine"])
    before = {"address": "Test entrance", "zipCode": None, "latitude": -8.7, "longitude": 115.1}
    after = dict(before, address="Test entrance corrected", latitude=-8.7001)
    with setup["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RESERVATION"].insert().values(
            reservation_id="location-test", uid_token="customer", spot_master_id="root", model_id="model",
            start_datetime=now() + timedelta(days=1), end_datetime=now() + timedelta(days=2), reservation_status="APPROVED",
            required_criteria_json={"pickupLocationSnapshot": before, "returnLocationSnapshot": before,
                                    "quote": {"finalTotal": 100}, "availabilityRequest": {"pickupLocation": "Customer address"}}))
    return {"bookedNo": "BOlocation-test", "changeType": "CORRECTION", "target": "PICKUP",
            "previousLocation": before, "correctedLocation": after, "reason": "Same entrance pin correction"}


def test_location_correction_has_audit_and_preserves_quote_and_delivery(client, signin, setup, correction):
    headers = signin()
    response = client.post("/nadreego/booking/location-correction", headers=headers, json=correction)
    assert response.status_code == 200, response.text
    with setup["engine"].connect() as conn:
        criteria = conn.scalar(select(metadata.tables["MSP_RESERVATION"].c.required_criteria_json))
    assert criteria["pickupLocationSnapshot"] == correction["correctedLocation"]
    assert criteria["returnLocationSnapshot"] == correction["previousLocation"]
    assert criteria["quote"] == {"finalTotal": 100}
    assert criteria["availabilityRequest"] == {"pickupLocation": "Customer address"}
    history = client.get("/nadreego/booking/BOlocation-test/location-corrections", headers=headers)
    assert history.status_code == 200
    record = history.json()["items"][0]
    assert record["before"] == correction["previousLocation"] and record["after"] == correction["correctedLocation"]
    assert record["changedBy"] == "primary"
    assert client.post("/nadreego/booking/location-correction", headers=headers, json=correction).status_code == 409


@pytest.mark.parametrize("user,code", [("general", 403), ("outsider", 404)])
def test_location_correction_scope(client, signin, correction, user, code):
    assert client.post("/nadreego/booking/location-correction", headers=signin(user), json=correction).status_code == code


@pytest.mark.parametrize("status", ["HANDED_OVER", "CANCELED", "EXPIRED", "RETURNED"])
def test_location_correction_does_not_rewrite_terminal_history(client, signin, setup, correction, status):
    with setup["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RESERVATION"].update().values(reservation_status=status))
    assert client.post("/nadreego/booking/location-correction", headers=signin(), json=correction).status_code == 409


def test_location_correction_rejects_relocation_and_invalid_coordinate(client, signin, correction):
    headers = signin()
    assert client.post("/nadreego/booking/location-correction", headers=headers,
                       json=dict(correction, changeType="RELOCATION")).status_code == 422
    invalid = dict(correction, correctedLocation=dict(correction["correctedLocation"], latitude=91))
    assert client.post("/nadreego/booking/location-correction", headers=headers, json=invalid).status_code == 422


def test_shop_relocation_leaves_existing_booking_unchanged(client, signin, setup, correction):
    response = client.post("/nadreego/shop/update", headers=signin(), json={"location": "New shop", "lat": -8.6, "lng": 115.3})
    assert response.status_code == 200
    with setup["engine"].connect() as conn:
        criteria = conn.scalar(select(metadata.tables["MSP_RESERVATION"].c.required_criteria_json))
    assert criteria["pickupLocationSnapshot"] == correction["previousLocation"]
