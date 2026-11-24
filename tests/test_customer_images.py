"""Customer display images use disposable SQLite and local synthetic SDK signing."""
from datetime import date, timedelta
from urllib.parse import unquote, urlsplit

import pytest
from sqlalchemy import event, select

from app.security import sign_user_access
from test_customer_receipt import at_period, new_quote, prepare, receive, submit
from test_external_reservations import approve, external, row
from test_images import image_urls
from test_pending_reservation_approval import pending_bookings

BASE = "/api/v1/nadree/rental"
MODEL_KEY = "models/customer-default.jpg"


@pytest.fixture
def customer_images(external, image_urls):
    ctx = external
    ctx["app"].state.images = image_urls
    keys = {ident: "vehicles/" + ident + "/actual.jpg" for ident in ctx["qrs"]}
    with ctx["engine"].begin() as connection:
        models, vehicles = ctx["tables"]["MSP_VEHICLE_MODEL"], ctx["tables"]["MSP_RENTAL_VEHICLE"]
        connection.execute(models.update().values(model_image_key=MODEL_KEY))
        for ident, key in keys.items():
            connection.execute(vehicles.update().where(vehicles.c.vehicle_id == ident).values(vehicle_image_key=key))
    return {**ctx, "image_keys": keys}


def assert_image(model, key):
    assert model["modelId"] == "pending-model"
    assert model["modelName"] == "Test" and model["cc"] == 125
    assert model["modelImageKey"] == key
    assert unquote(urlsplit(model["modelImageUrl"]).path) == "/" + key
    assert "vehicleImageKey" not in model and "vehicleImageUrl" not in model


def detail(ctx, ident):
    response = ctx["client"].get(BASE + "/reservations/" + ident, headers=ctx["headers"])
    assert response.status_code == 200, response.text
    return response.json()["item"]


def ongoing(ctx):
    response = ctx["client"].get(BASE + "/ongoing", headers=ctx["headers"])
    assert response.status_code == 200, response.text
    return response.json()["items"]


@pytest.mark.parametrize("vehicle_key", ["vehicles/qr-specific/front.jpg", None, ""])
def test_customer_qr_uses_selected_vehicle_photo_or_model_fallback(customer_images, vehicle_key):
    ctx = customer_images
    vehicle, qr = next(iter(ctx["qrs"].items()))
    table = ctx["tables"]["MSP_RENTAL_VEHICLE"]
    with ctx["engine"].begin() as connection:
        connection.execute(table.update().where(table.c.vehicle_id == vehicle).values(vehicle_image_key=vehicle_key))
    response = ctx["client"].post(BASE + "/qr/lookup", headers=ctx["headers"], json={"qrCode": qr})
    assert response.status_code == 200, response.text
    assert response.json()["vehicleId"] == vehicle
    assert_image(response.json()["model"], vehicle_key or MODEL_KEY)
    with ctx["engine"].connect() as connection:
        assert connection.scalar(select(table.c.vehicle_image_key).where(table.c.vehicle_id == vehicle)) == vehicle_key


def test_unassigned_reservation_and_model_availability_keep_model_photo(customer_images):
    ctx = customer_images
    ident = ctx["request_booking"](0)["reservationId"]
    assert row(ctx, ident)["assigned_vehicle_id"] is None
    assert_image(ongoing(ctx)[0]["model"], MODEL_KEY)
    assert_image(detail(ctx, ident)["model"], MODEL_KEY)
    start = date.today() + timedelta(days=7)
    response = ctx["client"].post(BASE + "/availability", json={
        "startDate": str(start), "returnDate": str(start + timedelta(days=3)),
        "minCc": 125, "maxCc": 125, "deliveryRequested": False})
    assert response.status_code == 200, response.text
    assert_image(response.json()["items"][0]["model"], MODEL_KEY)


@pytest.mark.parametrize("vehicle_key", ["vehicles/assigned/front.jpg", None, ""])
def test_assigned_reservation_list_and_detail_use_the_same_selected_image(customer_images, vehicle_key):
    ctx = customer_images
    ident = ctx["request_booking"](0)["reservationId"]
    assigned = approve(ctx, ident)["assigned_vehicle_id"]
    table = ctx["tables"]["MSP_RENTAL_VEHICLE"]
    with ctx["engine"].begin() as connection:
        connection.execute(table.update().where(table.c.vehicle_id == assigned).values(vehicle_image_key=vehicle_key))
    assert_image(ongoing(ctx)[0]["model"], vehicle_key or MODEL_KEY)
    assert_image(detail(ctx, ident)["model"], vehicle_key or MODEL_KEY)
    other = {"Authorization": "Bearer " + sign_user_access(ctx["settings"], "pending-user-1")}
    assert ctx["client"].get(BASE + "/reservations/" + ident, headers=other).status_code == 404
    with ctx["engine"].connect() as connection:
        assert connection.scalar(select(table.c.vehicle_image_key).where(table.c.vehicle_id == assigned)) == vehicle_key


def test_onsite_fixed_vehicle_photo_is_shown_before_assignment(customer_images):
    ctx = customer_images
    vehicle = list(ctx["qrs"])[-1]
    body, quote = new_quote(ctx, qr=ctx["qrs"][vehicle])
    response = submit(ctx, body, quote)
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    ident = item["reservationId"]
    saved = row(ctx, ident)
    assert saved["assigned_vehicle_id"] is None
    assert saved["required_criteria_json"]["onsiteVehicleId"] == vehicle
    for model in (item["model"], ongoing(ctx)[0]["model"], detail(ctx, ident)["model"]):
        assert_image(model, ctx["image_keys"][vehicle])


def test_receipt_and_rental_history_use_contract_vehicle_photo(customer_images, monkeypatch):
    ctx = customer_images
    ident = ctx["request_booking"](0)["reservationId"]
    assigned = approve(ctx, ident)["assigned_vehicle_id"]
    key = ctx["image_keys"][assigned]
    at_period(ctx, ident, monkeypatch)
    assert prepare(ctx, ident).status_code == 200
    received = receive(ctx, ident)
    assert received.status_code == 200, received.text
    assert received.json()["item"]["rentalStatus"] == "ON_RENT"
    assert_image(received.json()["item"]["model"], key)

    # A historical contract's actual vehicle takes precedence over an old
    # reservation assignment or onsite criteria naming a different vehicle.
    reservation = ctx["tables"]["MSP_RESERVATION"]
    saved = row(ctx, ident)
    others = [vehicle for vehicle in ctx["qrs"] if vehicle != assigned]
    with ctx["engine"].begin() as connection:
        connection.execute(reservation.update().where(reservation.c.reservation_id == ident).values(
            assigned_vehicle_id=others[0],
            required_criteria_json=dict(saved["required_criteria_json"], onsiteVehicleId=others[1])))
    assert_image(ongoing(ctx)[0]["model"], key)
    assert_image(detail(ctx, ident)["model"], key)
    with ctx["engine"].begin() as connection:
        connection.execute(reservation.update().where(reservation.c.reservation_id == ident).values(
            assigned_vehicle_id=assigned, required_criteria_json=saved["required_criteria_json"]))
    returned = ctx["client"].post("/nadreego/vehicle/return", headers=ctx["admin"],
        json={"qrCode": ctx["qrs"][assigned]})
    assert returned.status_code == 200, returned.text
    completed = ctx["client"].get(BASE + "/completed", headers=ctx["headers"])
    assert completed.status_code == 200, completed.text
    assert completed.json()["items"][0]["rentalStatus"] == "RETURNED"
    assert_image(completed.json()["items"][0]["model"], key)
    assert_image(detail(ctx, ident)["model"], key)


@pytest.mark.parametrize("invalid_key", ["models/not-a-vehicle-photo.jpg", "vehicles/../private.jpg"])
def test_invalid_vehicle_photo_is_not_replaced_with_another_image(customer_images, invalid_key):
    ctx = customer_images
    ident = ctx["request_booking"](0)["reservationId"]
    assigned = approve(ctx, ident)["assigned_vehicle_id"]
    table = ctx["tables"]["MSP_RENTAL_VEHICLE"]
    with ctx["engine"].begin() as connection:
        connection.execute(table.update().where(table.c.vehicle_id == assigned).values(vehicle_image_key=invalid_key))
    lookup = ctx["client"].post(BASE + "/qr/lookup", headers=ctx["headers"],
        json={"qrCode": ctx["qrs"][assigned]})
    assert lookup.status_code == 200, lookup.text
    for model in (lookup.json()["model"], ongoing(ctx)[0]["model"], detail(ctx, ident)["model"]):
        assert model["modelImageKey"] == invalid_key
        assert model["modelImageUrl"] is None


def test_reservation_list_fetches_vehicle_images_in_one_batch(customer_images):
    ctx = customer_images
    expected = {}
    for offset in (0, 4, 8):
        ident = ctx["request_booking"](0, offset=offset)["reservationId"]
        assigned = approve(ctx, ident)["assigned_vehicle_id"]
        expected[ident] = ctx["image_keys"][assigned]
    selects = []

    def capture_query(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT") and '"MSP_RENTAL_VEHICLE"' in statement:
            selects.append(statement)

    event.listen(ctx["engine"], "before_cursor_execute", capture_query)
    try:
        items = ongoing(ctx)
    finally:
        event.remove(ctx["engine"], "before_cursor_execute", capture_query)
    assert len(items) == 3
    assert len(selects) == 1
    for item in items:
        assert_image(item["model"], expected[item["reservationId"]])
