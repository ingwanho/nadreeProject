"""The shared model catalogue must not reveal another branch's inventory or prices."""
import pytest
from sqlalchemy import delete, update

from app.rental_schema import metadata
from app.security import now
from test_vehicle_qr import equipment


PATH = "/nadreego/brand"
BRANDS = ["Aster", "Boreal", "Zephyr"]
ORDERED = ["model-a-110", "model-a-150", "test-model", "model-b-300", "model-b-unknown", "model-z-160"]


@pytest.fixture
def catalog(setup, equipment):
    models = metadata.tables["MSP_VEHICLE_MODEL"]
    values = [
        ("test-model", "Aster", "Commuter 125", 125, 1),
        ("model-a-110", "Aster", "Commuter 110", 110, 1),
        ("model-a-150", "Aster", "Commuter 150", 150, 1),
        ("model-b-300", "Boreal", "Tourer 300", 300, 1),
        ("model-b-unknown", "Boreal", "Unspecified capacity", None, 1),
        ("model-z-160", "Zephyr", "City 160", 160, 1),
        ("model-hidden", "Hidden", "Inactive model", 125, 0),
    ]
    with setup["engine"].begin() as connection:
        for ident, brand, name, cc, active in values:
            fields = dict(brand=brand, model_name=name, cc=cc, is_active=active,
                vehicle_type="SCOOTER", model_image_key="catalog/" + ident + ".png")
            if ident == "test-model":
                connection.execute(models.update().where(models.c.model_id == ident).values(**fields))
            else:
                connection.execute(models.insert().values(model_id=ident, **fields))
        tiers = metadata.tables["MSP_RENTAL_TIER"]
        for spot, kind, low, high, price in (
            (None, "BASE", 0, 200, 10), ("root", "BASIC", 100, 130, 7),
            ("foreign", "BASIC", 100, 200, 99),
        ):
            connection.execute(tiers.insert().values(spot_master_id=spot, tier_type=kind,
                min_cc=low, max_cc=high, price=price))
    return {**setup, "equipment": equipment}


@pytest.fixture
def stocked_catalog(catalog):
    ctx, at = catalog, now()
    inventory = [
        ("own-a-premium", "root", "test-model", 80),
        ("own-b-basic", "root", "test-model", None),
        ("own-150-premium", "root", "model-a-150", 90),
        ("own-inactive-model", "root", "model-hidden", None),
        ("child-125", "child", "test-model", None),
        ("foreign-125-a", "foreign", "test-model", None),
        ("foreign-125-b", "foreign", "test-model", None),
        ("foreign-125-c", "foreign", "test-model", None),
    ]
    with ctx["engine"].begin() as connection:
        for ident, spot, model, premium in inventory:
            connection.execute(ctx["equipment"]["MSP_VEHICLE"].insert().values(
                vehicle_id=ident, vehicle_code=ident, plate_number=ident, vehicle_type="SCOOTER",
                model_name=model, is_active=1, created_at=at, updated_at=at))
            connection.execute(metadata.tables["MSP_RENTAL_VEHICLE"].insert().values(
                vehicle_id=ident, model_id=model, plate_number_full=ident, rental_enabled=1,
                price_type="BASIC" if premium is None else "PREMIUM", premium_daily_price=premium))
            connection.execute(metadata.tables["MSP_VEHICLE_STATUS"].insert().values(
                vehicle_id=ident, status="AVAILABLE", status_changed_at=at))
            connection.execute(ctx["equipment"]["MSP_VEHICLE_SPOT_HISTORY"].insert().values(
                vehicle_id=ident, spot_master_id=spot, assigned_at=at))
    return ctx


def request_catalog(client, headers, *, page=1, page_size=100):
    return client.post(PATH, headers=headers, json={"page": page, "pageSize": page_size})


def test_empty_branch_sees_all_active_brands_and_models_with_basic_prices(catalog, signin):
    headers = signin()

    response = request_catalog(catalog["client"], headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert set(data) == {"brand", "vehicle", "tier", "price", "page", "pageSize", "totalCount", "hasNext"}
    assert data["brand"] == BRANDS
    assert [item["modelId"] for item in data["vehicle"]] == ORDERED
    assert data["totalCount"] == 6 and data["page"] == 1 and data["pageSize"] == 100 and data["hasNext"] is False
    assert data["price"] is None
    assert all(item["vehicleCount"] == 0 for item in data["vehicle"])
    by_model = {item["modelId"]: item for item in data["vehicle"]}
    assert {key: item["price"] for key, item in by_model.items()} == {
        "test-model": 7, "model-a-110": 7, "model-a-150": 10,
        "model-b-300": None, "model-b-unknown": None, "model-z-160": 10,
    }
    assert by_model["test-model"] == {"modelId": "test-model", "brand": "Aster", "modelName": "Commuter 125",
        "cc": 125, "modelImageKey": "catalog/test-model.png", "modelImageUrl": None,
        "vehicleCount": 0, "price": 7}
    inventory = catalog["client"].post("/nadreego/vehicle/select", headers=headers, json={"page": 1, "pageSize": 100})
    assert inventory.status_code == 200 and inventory.json()["items"] == [] and inventory.json()["totalCount"] == 0


@pytest.mark.parametrize("page", [1, 2, 3, 99])
def test_model_pagination_never_truncates_global_brand_choices(catalog, signin, page):
    response = request_catalog(catalog["client"], signin(), page=page, page_size=2)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["brand"] == BRANDS
    assert [item["modelId"] for item in data["vehicle"]] == ORDERED[(page - 1) * 2:page * 2]
    assert data["totalCount"] == 6 and data["page"] == page and data["pageSize"] == 2
    assert data["hasNext"] is (page * 2 < 6)


@pytest.mark.parametrize("actor,count,basic,spot_code,owned", [
    ("primary", 2, 7, "CT1-ORG01", {"own-a-premium", "own-b-basic", "own-150-premium", "own-inactive-model"}),
    ("general", 2, 7, "CT1-ORG01", {"own-a-premium", "own-b-basic", "own-150-premium", "own-inactive-model"}),
    ("outsider", 3, 99, "CT2-ORG01", {"foreign-125-a", "foreign-125-b", "foreign-125-c"}),
])
def test_model_counts_and_basic_prices_are_direct_branch_only(stocked_catalog, signin, actor, count, basic, spot_code, owned):
    ctx, headers = stocked_catalog, signin(actor)

    response = request_catalog(ctx["client"], headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["brand"] == BRANDS and data["totalCount"] == 6
    by_model = {item["modelId"]: item for item in data["vehicle"]}
    assert list(by_model) == ORDERED
    assert by_model["test-model"]["vehicleCount"] == count
    assert by_model["test-model"]["price"] == basic
    assert by_model["model-a-150"]["vehicleCount"] == (0 if actor == "outsider" else 1)
    assert by_model["model-a-150"]["price"] == (99 if actor == "outsider" else 10)
    assert all(by_model[ident]["vehicleCount"] == 0 for ident in (
        "model-a-110", "model-b-300", "model-b-unknown", "model-z-160"))
    assert "model-hidden" not in by_model
    assert {(tier["type"], tier["price"], tier["spotCode"]) for tier in data["tier"]} == {
        ("BASE", 10, None), ("BASIC", basic, spot_code)}
    inventory = ctx["client"].post("/nadreego/vehicle/select", headers=headers, json={"page": 1, "pageSize": 100})
    assert inventory.status_code == 200, inventory.text
    assert {item["vehicle"]["vehicleId"] for item in inventory.json()["items"]} == owned
    assert inventory.json()["totalCount"] == len(owned)


def test_catalogue_does_not_turn_global_model_access_into_unauthenticated_access(catalog):
    response = request_catalog(catalog["client"], {})
    assert response.status_code == 401


def test_catalogue_still_rechecks_current_admin_branch_scope(catalog, signin):
    headers = signin()
    mapping = catalog["db"].table("MSP_ADMIN_SPOT_SCOPE")
    with catalog["engine"].begin() as connection:
        connection.execute(delete(mapping).where(mapping.c.admin_id == "primary", mapping.c.spot_master_id == "root"))

    response = request_catalog(catalog["client"], headers)

    assert response.status_code == 403 and response.json()["errorCode"] == "SPOT_ACCESS_DENIED"


def test_catalogue_price_is_null_when_shared_base_is_missing(catalog, signin):
    tiers = metadata.tables["MSP_RENTAL_TIER"]
    with catalog["engine"].begin() as connection:
        connection.execute(delete(tiers).where(tiers.c.tier_type == "BASE"))

    response = request_catalog(catalog["client"], signin())

    assert response.status_code == 200, response.text
    assert response.json()["brand"] == BRANDS and response.json()["totalCount"] == 6
    assert all(item["price"] is None for item in response.json()["vehicle"])


def test_all_inactive_catalogue_is_empty_without_hiding_actual_branch_vehicles(stocked_catalog, signin):
    ctx, headers = stocked_catalog, signin()
    models = metadata.tables["MSP_VEHICLE_MODEL"]
    with ctx["engine"].begin() as connection:
        connection.execute(update(models).values(is_active=0))

    response = request_catalog(ctx["client"], headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["brand"] == [] and data["vehicle"] == [] and data["totalCount"] == 0 and data["hasNext"] is False
    inventory = ctx["client"].post("/nadreego/vehicle/select", headers=headers, json={"page": 1, "pageSize": 100})
    assert inventory.status_code == 200 and inventory.json()["totalCount"] == 4
