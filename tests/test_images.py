"""Use real SDK signing with synthetic credentials; never contact AWS or an image host."""
from datetime import date, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import NoCredentialsError
from pydantic import ValidationError
import pytest

from app.config import Settings
from app.images import ImageURLs
from app.rental_schema import metadata
from test_vehicle_qr import equipment


@pytest.fixture
def image_urls():
    settings = Settings(_env_file=None, s3_image_bucket="nadree-vehicle-img",
                        s3_image_region="ap-northeast-2")
    client = boto3.session.Session(aws_access_key_id="test-access-not-real",
        aws_secret_access_key="test-secret-not-real", aws_session_token="test-session-not-real").client(
            "s3", region_name=settings.s3_image_region, config=Config(signature_version="s3v4"))
    urls = ImageURLs(settings, client=client)
    yield urls
    urls.close()


@pytest.mark.parametrize("method,key", [
    ("model_url", "models/honda/vario 125.jpg"),
    ("vehicle_url", "vehicles/vehicle-1/차량 앞면.png"),
])
def test_sdk_signs_the_exact_object_key_without_remote_lookups(image_urls, monkeypatch, method, key):
    def no_remote_calls(*args, **kwargs):
        pytest.fail("URL generation must not read S3 objects")
    monkeypatch.setattr(image_urls._client, "head_object", no_remote_calls)
    monkeypatch.setattr(image_urls._client, "get_object", no_remote_calls)
    parsed = urlsplit(getattr(image_urls, method)(key))
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https" and "nadree-vehicle-img" in parsed.netloc
    assert unquote(parsed.path) == "/" + key
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Expires"] == ["900"]
    assert "/ap-northeast-2/s3/aws4_request" in query["X-Amz-Credential"][0]
    assert len(query["X-Amz-Signature"][0]) == 64
    assert query["X-Amz-Security-Token"] == ["test-session-not-real"]


def test_lazy_client_signs_regional_s3_host_without_redirects(monkeypatch, tmp_path):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-not-real")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-not-real")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "test-session-not-real")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))

    def no_remote_calls(*args, **kwargs):
        pytest.fail("Regional URL generation must not contact AWS")

    monkeypatch.setattr("botocore.client.BaseClient._make_api_call", no_remote_calls)
    images = ImageURLs(Settings(_env_file=None, s3_image_bucket="nadree-vehicle-img",
        s3_image_region="ap-northeast-2"))
    assert images._client is None
    try:
        parsed = urlsplit(images.model_url("models/reviewed-model.jpg"))
        query = parse_qs(parsed.query)
        assert parsed.netloc == "nadree-vehicle-img.s3.ap-northeast-2.amazonaws.com"
        assert parsed.path == "/models/reviewed-model.jpg"
        assert "/ap-northeast-2/s3/aws4_request" in query["X-Amz-Credential"][0]
        assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
        assert query["X-Amz-Security-Token"] == ["test-session-not-real"]
    finally:
        images.close()


@pytest.mark.parametrize("method,key", [
    ("model_url", None), ("vehicle_url", ""),
    ("model_url", "vehicles/private.jpg"), ("vehicle_url", "models/vario.jpg"),
    ("model_url", "passport/private.jpg"), ("model_url", "models/../passport/private.jpg"),
    ("vehicle_url", "vehicles/./front.jpg"), ("model_url", "/models/vario.jpg"),
    ("model_url", "models/"), ("model_url", "models/" + "가" * 400),
    ("vehicle_url", "vehicles/a\x00.jpg"), ("model_url", "https://example.com/a\n.jpg"),
    ("model_url", "http://example.com/a.jpg"),
    ("model_url", "https://user:password@example.com/a.jpg"),
    ("model_url", "s3://other-bucket/models/a.jpg"),
])
def test_empty_invalid_or_other_namespace_keys_never_receive_signed_access(image_urls, method, key):
    assert getattr(image_urls, method)(key) is None


def test_unconfigured_images_do_not_initialize_aws_and_preserve_public_https_urls(monkeypatch):
    def unexpected_client(*args, **kwargs):
        pytest.fail("Unconfigured images must not load credentials or contact metadata")
    monkeypatch.setattr("app.images.boto3.session.Session", unexpected_client)
    images = ImageURLs(Settings(_env_file=None))
    assert images.model_url("models/a.jpg") is None
    assert images.vehicle_url("vehicles/a.jpg") is None
    url = "https://placehold.co/640x480/png?text=model"
    assert images.model_url(url) == url
    assert images.vehicle_url(url) == url


def test_signing_failure_is_optional_and_does_not_log_object_keys_or_credentials(caplog):
    class MissingCredentials:
        def generate_presigned_url(self, *args, **kwargs):
            raise NoCredentialsError()
    images = ImageURLs(Settings(_env_file=None, s3_image_bucket="nadree-vehicle-img",
        s3_image_region="ap-northeast-2"), client=MissingCredentials())
    assert images.vehicle_url("vehicles/private-object-name.jpg") is None
    assert "NoCredentialsError" in caplog.text
    assert "private-object-name" not in caplog.text and "X-Amz" not in caplog.text


@pytest.mark.parametrize("values", [
    {"s3_image_bucket": "nadreeVehicleImg"},
    {"s3_image_url_ttl_seconds": 0}, {"s3_image_url_ttl_seconds": 3601},
])
def test_image_configuration_rejects_invalid_bucket_case_and_expiration(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


@pytest.fixture
def image_vehicle(setup, equipment, signin, image_urls):
    setup["app"].state.images = image_urls
    model_key = "models/test-model.jpg"
    vehicle_key = "vehicles/test-vehicle/front.jpg"
    with setup["engine"].begin() as connection:
        connection.execute(metadata.tables["MSP_VEHICLE_MODEL"].update().values(
            cc=125, model_image_key=model_key))
        connection.execute(metadata.tables["MSP_RENTAL_TIER"].insert().values(
            tier_type="BASE", spot_master_id=None, min_cc=0, max_cc=200, price=25))
    headers = signin()
    created = setup["client"].post("/nadreego/vehicle/create", headers=headers, json={
        "qrToken": "NDR-Ab12Cd34", "brand": "Test", "vehicleName": "Test model",
        "modelId": "test-model", "plateNumber": "IMAGE-TEST", "vehicleImageKey": vehicle_key})
    assert created.status_code == 200, created.text
    return setup, headers, model_key, vehicle_key


def test_admin_catalog_inventory_calendar_and_qr_keep_keys_and_expose_image_urls(image_vehicle):
    ctx, headers, model_key, vehicle_key = image_vehicle
    client = ctx["client"]
    page = {"page": 1, "pageSize": 20}
    catalog = client.post("/nadreego/brand", headers=headers, json=page)
    assert catalog.status_code == 200, catalog.text
    model = catalog.json()["vehicle"][0]
    assert model["modelImageKey"] == model_key and model["modelImageUrl"].startswith("https://")
    inventory = client.post("/nadreego/vehicle/select", headers=headers, json=page)
    assert inventory.status_code == 200, inventory.text
    item = inventory.json()["items"][0]
    assert item["modelImageKey"] == model_key and item["modelImageUrl"].startswith("https://")
    assert item["vehicle"]["vehicleImageKey"] == vehicle_key
    assert unquote(urlsplit(item["vehicle"]["vehicleImageUrl"]).path) == "/" + vehicle_key
    tomorrow = date.today() + timedelta(days=1)
    calendar = client.post("/nadreego/main/calendar", headers=headers,
        json={**page, "startDate": tomorrow.isoformat(), "endDate": (tomorrow + timedelta(days=1)).isoformat()})
    assert calendar.status_code == 200, calendar.text
    assert calendar.json()["items"][0]["vehicleImageUrl"].startswith("https://")
    qr = client.post("/nadreego/vehicle/qr/validate", headers=headers, json={"qrCode": "NDR-Ab12Cd34"})
    assert qr.status_code == 200, qr.text
    assert qr.json()["data"]["vehicle"]["vehicleImageKey"] == vehicle_key
    assert qr.json()["data"]["vehicle"]["vehicleImageUrl"].startswith("https://")


def test_customer_public_availability_preserves_key_and_model_url_through_response_schema(image_vehicle):
    ctx, _headers, model_key, _vehicle_key = image_vehicle
    tomorrow = date.today() + timedelta(days=1)
    response = ctx["client"].post("/api/v1/nadree/rental/availability", json={
        "startDate": tomorrow.isoformat(), "returnDate": (tomorrow + timedelta(days=3)).isoformat(),
        "minCc": 125, "maxCc": 125, "deliveryRequested": False})
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1
    model = response.json()["items"][0]["model"]
    assert model["modelImageKey"] == model_key
    assert model["modelImageUrl"].startswith("https://")


def test_unavailable_credentials_do_not_break_vehicle_queries(image_vehicle):
    ctx, headers, model_key, vehicle_key = image_vehicle
    class MissingCredentials:
        def generate_presigned_url(self, *args, **kwargs):
            raise NoCredentialsError()
        def close(self):
            pass
    ctx["app"].state.images._client = MissingCredentials()
    response = ctx["client"].post("/nadreego/vehicle/select", headers=headers, json={"page": 1, "pageSize": 20})
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["modelImageKey"] == model_key and item["modelImageUrl"] is None
    assert item["vehicle"]["vehicleImageKey"] == vehicle_key and item["vehicle"]["vehicleImageUrl"] is None


@pytest.mark.parametrize("vehicle_key", [None, ""])
@pytest.mark.parametrize("model_key", ["models/test-model.jpg", "https://example.com/model.jpg"])
def test_absent_vehicle_photo_uses_model_image_in_inventory_calendar_and_qr(image_vehicle, vehicle_key, model_key):
    ctx, headers, _old_model_key, _old_vehicle_key = image_vehicle
    with ctx["engine"].begin() as connection:
        connection.execute(metadata.tables["MSP_RENTAL_VEHICLE"].update().values(vehicle_image_key=vehicle_key))
        connection.execute(metadata.tables["MSP_VEHICLE_MODEL"].update().values(model_image_key=model_key))
    page = {"page": 1, "pageSize": 20}
    inventory = ctx["client"].post("/nadreego/vehicle/select", headers=headers, json=page)
    assert inventory.status_code == 200, inventory.text
    item = inventory.json()["items"][0]
    assert item["modelImageKey"] == model_key
    tomorrow = date.today() + timedelta(days=1)
    calendar = ctx["client"].post("/nadreego/main/calendar", headers=headers, json={
        **page, "startDate": tomorrow.isoformat(), "endDate": (tomorrow + timedelta(days=1)).isoformat()})
    assert calendar.status_code == 200, calendar.text
    qr = ctx["client"].post("/nadreego/vehicle/qr/validate", headers=headers, json={"qrCode": "NDR-Ab12Cd34"})
    assert qr.status_code == 200, qr.text
    for vehicle in (item["vehicle"], calendar.json()["items"][0], qr.json()["data"]["vehicle"]):
        assert vehicle["vehicleImageKey"] == model_key
        if model_key.startswith("https://"):
            assert vehicle["vehicleImageUrl"] == model_key
        else:
            assert unquote(urlsplit(vehicle["vehicleImageUrl"]).path) == "/" + model_key
    with ctx["engine"].connect() as connection:
        # A display fallback must never replace the vehicle's own stored key.
        stored = connection.execute(metadata.tables["MSP_RENTAL_VEHICLE"].select()).mappings().one()
        assert stored["vehicle_image_key"] == vehicle_key


@pytest.mark.parametrize("vehicle_key", ["models/not-a-vehicle-photo.jpg", "vehicles/../passport/private.jpg"])
def test_invalid_configured_vehicle_photo_is_not_hidden_by_model_fallback(image_vehicle, vehicle_key):
    ctx, headers, model_key, _old_vehicle_key = image_vehicle
    with ctx["engine"].begin() as connection:
        connection.execute(metadata.tables["MSP_RENTAL_VEHICLE"].update().values(vehicle_image_key=vehicle_key))
    response = ctx["client"].post("/nadreego/vehicle/select", headers=headers, json={"page": 1, "pageSize": 20})
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert unquote(urlsplit(item["modelImageUrl"]).path) == "/" + model_key
    assert item["vehicle"]["vehicleImageKey"] == vehicle_key
    assert item["vehicle"]["vehicleImageUrl"] is None


def test_vehicle_signing_failure_does_not_fall_back_to_public_model_image(image_vehicle):
    ctx, headers, _model_key, vehicle_key = image_vehicle
    public_model_image = "https://example.com/test-model.jpg"
    with ctx["engine"].begin() as connection:
        connection.execute(metadata.tables["MSP_VEHICLE_MODEL"].update().values(model_image_key=public_model_image))

    class MissingCredentials:
        def generate_presigned_url(self, *args, **kwargs):
            raise NoCredentialsError()
        def close(self):
            pass

    ctx["app"].state.images._client = MissingCredentials()
    response = ctx["client"].post("/nadreego/vehicle/select", headers=headers, json={"page": 1, "pageSize": 20})
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["modelImageUrl"] == public_model_image
    assert item["vehicle"]["vehicleImageKey"] == vehicle_key
    assert item["vehicle"]["vehicleImageUrl"] is None


@pytest.mark.parametrize("model_key", [None, "vehicles/not-a-model-photo.jpg"])
def test_missing_vehicle_photo_with_unusable_model_image_keeps_query_successful(image_vehicle, model_key):
    ctx, headers, _old_model_key, _vehicle_key = image_vehicle
    with ctx["engine"].begin() as connection:
        connection.execute(metadata.tables["MSP_RENTAL_VEHICLE"].update().values(vehicle_image_key=None))
        connection.execute(metadata.tables["MSP_VEHICLE_MODEL"].update().values(model_image_key=model_key))
    response = ctx["client"].post("/nadreego/vehicle/select", headers=headers, json={"page": 1, "pageSize": 20})
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["modelImageKey"] == model_key and item["modelImageUrl"] is None
    assert item["vehicle"]["vehicleImageKey"] == model_key and item["vehicle"]["vehicleImageUrl"] is None
