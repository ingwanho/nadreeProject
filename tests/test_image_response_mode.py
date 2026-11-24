"""Retired test settings cannot swap normal image keys and URLs."""
from datetime import date, timedelta
from urllib.parse import unquote, urlsplit

from botocore.exceptions import NoCredentialsError
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.rental_schema import metadata
from test_customer_images import customer_images, detail, ongoing, MODEL_KEY
from test_customer_receipt import at_period, prepare, receive
from test_external_reservations import approve, external, operation
from test_images import image_urls, image_vehicle
from test_pending_reservation_approval import pending_bookings
from test_vehicle_qr import equipment

BASE = "/api/v1/nadree/rental"


def test_swagger_uses_normal_layout_even_with_deprecated_env():
    settings = Settings(_env_file=None, image_response_test_swap=True)
    with TestClient(create_app(settings=settings)) as client:
        spec = client.get("/openapi.json").json()
    assert "TEMPORARY TEST IMAGE FIELD SWAP ENABLED" not in spec["info"]["description"]
    assert "NADREE_IMAGE_RESPONSE_TEST_SWAP=false" not in spec["info"]["description"]
    properties = spec["components"]["schemas"]["CustomerModel"]["properties"]
    assert "modelImageKey" in properties and "modelImageUrl" in properties


def assert_normal(view, prefix, selected):
    assert view[prefix + "ImageKey"] == selected
    address = view[prefix + "ImageUrl"]
    assert address.startswith("https://")
    assert unquote(urlsplit(address).path) == "/" + selected


@pytest.mark.parametrize("own_photo", [True, False])
def test_admin_test_layout_and_recovery_preserve_selection_and_storage(image_vehicle, own_photo):
    ctx, headers, model_key, vehicle_key = image_vehicle
    assert Settings(_env_file=None).image_response_test_swap is False
    stored_key = vehicle_key if own_photo else None
    selected = stored_key or model_key
    with ctx["engine"].begin() as connection:
        connection.execute(metadata.tables["MSP_RENTAL_VEHICLE"].update().values(vehicle_image_key=stored_key))
    ctx["settings"].image_response_test_swap = True
    page = {"page": 1, "pageSize": 20}
    catalog = ctx["client"].post("/nadreego/brand", headers=headers, json=page)
    assert catalog.status_code == 200
    assert_normal(catalog.json()["vehicle"][0], "model", model_key)
    inventory = ctx["client"].post("/nadreego/vehicle/select", headers=headers, json=page)
    assert inventory.status_code == 200
    item = inventory.json()["items"][0]
    assert_normal(item, "model", model_key)
    assert_normal(item["vehicle"], "vehicle", selected)
    tomorrow = date.today() + timedelta(days=1)
    for extra in ({}, {"vehicleStatus": "AVAILABLE"}):
        calendar = ctx["client"].post("/nadreego/main/calendar", headers=headers, json={
            **page, "startDate": str(tomorrow), "endDate": str(tomorrow + timedelta(days=1)), **extra})
        assert calendar.status_code == 200, calendar.text
        assert_normal(calendar.json()["items"][0], "vehicle", selected)
    qr = ctx["client"].post("/nadreego/vehicle/qr/validate", headers=headers,
        json={"qrCode": "NDR-Ab12Cd34"})
    assert qr.status_code == 200
    assert_normal(qr.json()["data"]["vehicle"], "vehicle", selected)
    with ctx["engine"].connect() as connection:
        saved = connection.execute(metadata.tables["MSP_RENTAL_VEHICLE"].select()).mappings().one()
        assert saved["vehicle_image_key"] == stored_key
    # Both values of the retired switch preserve the normal layout without DB writes.
    ctx["settings"].image_response_test_swap = False
    restored = ctx["client"].post("/nadreego/vehicle/select", headers=headers, json=page).json()["items"][0]
    assert restored["vehicle"]["vehicleImageKey"] == selected
    assert unquote(urlsplit(restored["vehicle"]["vehicleImageUrl"]).path) == "/" + selected


@pytest.mark.parametrize("own_photo", [True, False])
def test_customer_test_layout_survives_schema_and_receipt_flow(customer_images, monkeypatch, own_photo):
    ctx = customer_images
    ctx["settings"].image_response_test_swap = True
    if not own_photo:
        with ctx["engine"].begin() as connection:
            connection.execute(ctx["tables"]["MSP_RENTAL_VEHICLE"].update().values(vehicle_image_key=None))
    future = date.today() + timedelta(days=7)
    available = ctx["client"].post(BASE + "/availability", json={"startDate": str(future),
        "returnDate": str(future + timedelta(days=1)), "minCc": 125, "maxCc": 125, "deliveryRequested": False})
    assert available.status_code == 200
    assert_normal(available.json()["items"][0]["model"], "model", MODEL_KEY)
    ident = ctx["request_booking"](0)["reservationId"]
    assert_normal(detail(ctx, ident)["model"], "model", MODEL_KEY)
    assigned = approve(ctx, ident)["assigned_vehicle_id"]
    selected = ctx["image_keys"][assigned] if own_photo else MODEL_KEY
    for model in (detail(ctx, ident)["model"], ongoing(ctx)[0]["model"]):
        assert_normal(model, "model", selected)
    lookup = ctx["client"].post(BASE + "/qr/lookup", headers=ctx["headers"],
        json={"qrCode": ctx["qrs"][assigned]})
    assert lookup.status_code == 200
    assert_normal(lookup.json()["model"], "model", selected)
    assert_normal(operation(ctx, ident)["vehicle"], "vehicle", selected)
    at_period(ctx, ident, monkeypatch)
    assert prepare(ctx, ident).status_code == 200
    received = receive(ctx, ident)
    assert received.status_code == 200
    assert_normal(received.json()["item"]["model"], "model", selected)
    returned = ctx["client"].post("/nadreego/vehicle/return", headers=ctx["admin"],
        json={"qrCode": ctx["qrs"][assigned]})
    assert returned.status_code == 200
    completed = ctx["client"].get(BASE + "/completed", headers=ctx["headers"])
    assert completed.status_code == 200
    assert_normal(completed.json()["items"][0]["model"], "model", selected)
    with ctx["engine"].connect() as connection:
        saved = connection.scalar(select(ctx["tables"]["MSP_RENTAL_VEHICLE"].c.vehicle_image_key).where(
            ctx["tables"]["MSP_RENTAL_VEHICLE"].c.vehicle_id == assigned))
        assert saved == (ctx["image_keys"][assigned] if own_photo else None)


def test_test_layout_keeps_signing_failure_out_of_display_key(image_vehicle):
    ctx, headers, model_key, vehicle_key = image_vehicle
    ctx["settings"].image_response_test_swap = True

    class MissingCredentials:
        def generate_presigned_url(self, *args, **kwargs):
            raise NoCredentialsError()

        def close(self):
            pass

    ctx["app"].state.images._client = MissingCredentials()
    response = ctx["client"].post("/nadreego/vehicle/select", headers=headers,
        json={"page": 1, "pageSize": 20})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["modelImageKey"] == model_key and item["modelImageUrl"] is None
    assert item["vehicle"]["vehicleImageKey"] == vehicle_key and item["vehicle"]["vehicleImageUrl"] is None


def test_test_layout_does_not_change_vehicle_registration_input(image_vehicle):
    ctx, headers, _model_key, _vehicle_key = image_vehicle
    ctx["settings"].image_response_test_swap = True
    uploaded_key = "vehicles/new-registration/front.jpg"
    response = ctx["client"].post("/nadreego/vehicle/create", headers=headers, json={
        "qrToken": "NDR-NewPhoto5678", "brand": "Test", "vehicleName": "Test model",
        "modelId": "test-model", "plateNumber": "IMAGE-NEW", "vehicleImageKey": uploaded_key})
    assert response.status_code == 200, response.text
    with ctx["engine"].connect() as connection:
        keys = list(connection.scalars(select(metadata.tables["MSP_RENTAL_VEHICLE"].c.vehicle_image_key)))
        assert uploaded_key in keys
