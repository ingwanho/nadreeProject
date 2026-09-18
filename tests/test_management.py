from datetime import date, timedelta

import pytest
from sqlalchemy import Table, delete, func, select, update

from app.security import GENERAL, PRIMARY, now


def count(setup, name):
    with setup["engine"].connect() as conn:
        return conn.scalar(select(func.count()).select_from(setup["db"].table(name)))


def test_hierarchy_is_limited_to_descendants(client, signin):
    response = client.get("/api/v1/organizations/spots/hierarchy", headers=signin())
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [row["spot_master_id"] for row in response.json()["items"]] == ["child"]
    page = client.get("/api/v1/organizations/spots/hierarchy?offset=1&limit=1", headers=signin())
    assert page.json() == {"items": [], "total": 1}


def test_admin_list_contains_only_current_branch(client, signin):
    response = client.get("/nadreego/shop/admin", headers=signin("general"))
    assert {row["adminId"] for row in response.json()["admin"]} == {"primary", "general", "general2"}


@pytest.mark.parametrize("query,total", [("search=child", 1), ("search=foreign", 0), ("search=%25", 0),
    ("unit_type=spot", 1), ("unit_type=region", 0), ("is_active=0", 0), ("has_manager=1", 0), ("has_manager=0", 1)])
def test_hierarchy_filters_apply_before_total_and_pagination(client, signin, query, total):
    result = client.get("/api/v1/organizations/spots/hierarchy?" + query, headers=signin())
    assert result.status_code == 200 and result.json()["total"] == total


@pytest.mark.parametrize("path,body", [
    ("/nadreego/admin/roleChange", {"adminId": "general2"}),
    ("/nadreego/shop/adminDelete", {"adminId": "general2"}),
    ("/nadreego/shop/update", {"shopName": "Not allowed"}),
    ("/api/v1/organizations/spots", {"spot_name": "Not allowed", "unit_type": "spot", "parent_spot_id": "root"}),
    ("/nadreego/shop/adminRequestAction", {"email": "new@example.com", "action": "APPROVE"}),
])
def test_general_admin_cannot_perform_primary_actions(client, signin, path, body):
    result = client.post(path, headers=signin("general"), json=body)
    assert result.status_code == 403 and result.json()["errorCode"] == "PRIMARY_ADMIN_REQUIRED"


@pytest.mark.parametrize("path", ["/nadreego/admin/roleChange", "/nadreego/shop/adminDelete"])
def test_admin_actions_reject_foreign_branch(client, signin, path):
    assert client.post(path, headers=signin(), json={"adminId": "outsider"}).status_code == 404


def test_role_transfer_changes_both_roles_and_old_token_permissions(client, signin, setup):
    first, second = signin(), signin("general")
    result = client.post("/nadreego/admin/roleChange", headers=first, json={"adminId": "general"})
    assert result.json() == {"status": "success", "primaryAdminId": "general"}
    rows = client.get("/nadreego/shop/admin", headers=first).json()["admin"]
    assert [row["adminId"] for row in rows if row["role"] == PRIMARY] == ["general"]
    assert client.post("/nadreego/shop/update", headers=first, json={"shopName": "Denied"}).status_code == 403
    assert client.post("/nadreego/admin/roleChange", headers=second, json={"adminId": "primary"}).status_code == 200


def test_inconsistent_multiple_primaries_reject_transfer(client, signin, setup):
    headers = signin()
    table = setup["db"].table("MSP_ADMIN_ROLE")
    with setup["engine"].begin() as conn:
        conn.execute(update(table).where(table.c.admin_id == "general2").values(role_code=PRIMARY))
    result = client.post("/nadreego/admin/roleChange", headers=headers, json={"adminId": "general"})
    assert result.json()["errorCode"] == "PRIMARY_ADMIN_INCONSISTENT"


def test_admin_removal_preserves_shared_identity_and_web_role(client, signin, setup):
    headers, removed = signin(), signin("general", fcmToken="removed-device")
    mapping = setup["db"].table("MSP_ADMIN_ROLE")
    with setup["engine"].begin() as conn:
        conn.execute(mapping.insert().values(admin_id="general", role_code="viewer", assigned_at=now()))
    result = client.post("/nadreego/shop/adminDelete", headers=headers, json={"adminId": "general"})
    assert result.status_code == 200
    admins = setup["db"].table("MSP_ADMIN")
    with setup["engine"].connect() as conn:
        row = conn.execute(select(admins).where(admins.c.admin_id == "general")).mappings().one()
        granted = set(conn.scalars(select(mapping.c.role_code).where(mapping.c.admin_id == "general")))
    assert row["is_active"] == 1 and row["fcm_token"] is None
    assert granted == {"viewer"}
    assert client.get("/nadreego/shop/admin", headers=removed).status_code == 401
    assert client.post("/nadreego/shop/adminDelete", headers=headers, json={"adminId": "primary"}).status_code == 409


@pytest.mark.parametrize("table_name,values,code", [
    ("MSP_SPOT_MASTER", {"is_active": 0}, "SPOT_UNAVAILABLE"),
    ("MSP_SPOT_MASTER", {"contract_end": date.today() - timedelta(days=1)}, "SPOT_CONTRACT_INACTIVE"),
    ("MSP_CONTRACT", {"status": "terminated"}, "SPOT_CONTRACT_INACTIVE"),
])
def test_inactive_spot_or_contract_is_denied(client, signin, setup, table_name, values, code):
    headers = signin()
    with setup["engine"].begin() as conn:
        conn.execute(update(setup["db"].table(table_name)).values(**values))
    result = client.get("/nadreego/shop/admin", headers=headers)
    assert result.status_code == 403 and result.json()["errorCode"] == code


def test_scope_is_required_in_addition_to_primary_spot_and_role(client, signin, setup):
    headers = signin()
    scope = setup["db"].table("MSP_ADMIN_SPOT_SCOPE")
    with setup["engine"].begin() as conn:
        conn.execute(delete(scope).where(scope.c.admin_id == "primary"))
    result = client.get("/nadreego/shop/admin", headers=headers)
    assert result.json()["errorCode"] == "SPOT_ACCESS_DENIED"


def test_shop_updates_normalized_master_and_delivery(client, signin, setup):
    response = client.post("/nadreego/shop/update", headers=signin(),
        json={"shopName": "New name", "location": "New address", "contact": "12345", "deliveryServiceType": "START_ONLY"})
    assert response.json() == {"status": "success", "spotMasterId": "root", "deliveryServiceType": "START_ONLY"}
    with setup["engine"].connect() as conn:
        master, normalized = setup["db"].table("MSP_SPOT_MASTER"), setup["db"].table("MSP_ORG")
        row = conn.execute(select(master).where(master.c.spot_master_id == "root")).mappings().one()
        child_name = conn.scalar(select(master.c.org_name).where(master.c.spot_master_id == "child"))
        name = conn.scalar(select(normalized.c.org_name).where(normalized.c.org_id == "root"))
    assert row["spot_name"] == row["unit_name"] == child_name == name == "New name"


@pytest.mark.parametrize("body", [{"introduction": "Not mapped", "shopName": "Must not change"}, {"email": "shop@example.com"}])
def test_unmapped_shop_fields_fail_without_partial_write(client, signin, setup, body):
    rent = setup["db"].table("MSP_SPOT_RENT")
    old_columns = [name for name in rent.c.keys() if name not in ["introduction", "contact_email"]]
    setup["db"].metadata.remove(rent)
    Table("MSP_SPOT_RENT", setup["db"].metadata, autoload_with=setup["engine"], include_columns=old_columns)
    response = client.post("/nadreego/shop/update", headers=signin(), json=body)
    assert response.status_code == 503 and response.json()["errorCode"] == "SCHEMA_MAPPING_REQUIRED"
    table = setup["db"].table("MSP_SPOT_MASTER")
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(table.c.spot_name).where(table.c.spot_master_id == "root")) == "root"


def test_shop_profile_columns_store_and_preserve_other_values(client, signin, setup):
    headers = signin()
    table = setup["db"].table("MSP_SPOT_RENT")
    response = client.post("/nadreego/shop/update", headers=headers,
        json={"introduction": "Branch introduction", "email": "branch@example.com", "shopName": "Updated branch"})
    assert response.status_code == 200 and response.json()["status"] == "success"
    assert client.post("/nadreego/shop/update", headers=headers, json={"contact": "12345"}).status_code == 200
    with setup["engine"].connect() as conn:
        row = conn.execute(select(table).where(table.c.spot_master_id == "root")).mappings().one()
        other = conn.execute(select(table).where(table.c.spot_master_id == "child")).mappings().one()
    assert row["introduction"] == "Branch introduction" and row["contact_email"] == "branch@example.com"
    assert other["introduction"] is None and other["contact_email"] is None


@pytest.mark.parametrize("field,limit", [("introduction", 500), ("email", 200)])
def test_shop_profile_length_limits_are_atomic(client, signin, setup, field, limit):
    headers = signin()
    response = client.post("/nadreego/shop/update", headers=headers, json={field: "a" * limit})
    assert response.status_code == 200
    response = client.post("/nadreego/shop/update", headers=headers, json={field: "a" * (limit + 1), "shopName": "Not saved"})
    assert response.status_code == 422
    table, master = setup["db"].table("MSP_SPOT_RENT"), setup["db"].table("MSP_SPOT_MASTER")
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(table.c["contact_email" if field == "email" else field]).where(table.c.spot_master_id == "root")) == "a" * limit
        assert conn.scalar(select(master.c.spot_name).where(master.c.spot_master_id == "root")) == "root"


@pytest.mark.parametrize("unit_type", ["region", "local", "spot", "team", "agency"])
def test_create_child_persists_normalized_rows_and_rental_sidecar(client, signin, setup, unit_type):
    response = client.post("/api/v1/organizations/spots", headers=signin(),
        json={"spot_name": "New child", "unit_type": unit_type, "parent_spot_id": "root", "lat": -8.65, "lng": 115.2})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["unit_code"].startswith("CT1-ORG01-") and result["spot_id"]
    assert result["lat"] == -8.65 and result["lng"] == 115.2
    master, rent = setup["db"].table("MSP_SPOT_MASTER"), setup["db"].table("MSP_SPOT_RENT")
    with setup["engine"].connect() as conn:
        row = conn.execute(select(master).where(master.c.spot_master_id == result["spot_id"])).mappings().one()
        assert row["contract_id"] == "CT1"
        assert conn.scalar(select(rent.c.delivery_service_type).where(rent.c.spot_master_id == result["spot_id"])) == "NONE"
        if unit_type in ["region", "local", "spot"]:
            normal = setup["db"].table("MSP_" + unit_type.upper())
            assert conn.scalar(select(normal.c[unit_type + "_name"]).where(normal.c[unit_type + "_id"] == result["spot_id"])) == "New child"


@pytest.mark.parametrize("body,status", [
    ({"parent_spot_id": "foreign"}, 404), ({"parent_spot_id": "sibling"}, 404),
    ({"unit_type": "org"}, 403), ({"address": "x" * 301}, 422),
    ({"contract_end": (date.today() + timedelta(days=400)).isoformat()}, 422),
    ({"contract_start": (date.today() - timedelta(days=400)).isoformat()}, 422),
    ({"lat": 100}, 422),
])
def test_invalid_child_creation_is_atomic(client, signin, setup, body, status):
    before = count(setup, "MSP_SPOT_MASTER")
    result = client.post("/api/v1/organizations/spots", headers=signin(),
        json={"spot_name": "Child", "parent_spot_id": "root", "unit_type": "spot", **body})
    assert result.status_code == status, result.text
    assert count(setup, "MSP_SPOT_MASTER") == before


def test_signup_request_routes_do_not_treat_disabled_accounts_as_requests(client, signin):
    headers = signin()
    assert client.get("/nadreego/shop/adminRequest", headers=headers).json() == {"status": "success", "admins": []}
    assert client.post("/nadreego/shop/adminRequestAction", headers=headers,
        json={"email": "general@example.com", "action": "APPROVE"}).json()["errorCode"] == "ADMIN_REQUEST_NOT_FOUND"
    assert client.get("/nadreego/shop/adminRequest", headers=signin("general")).status_code == 403
