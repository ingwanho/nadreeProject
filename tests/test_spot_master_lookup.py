"""Public parent IDs address MSP_SPOT_MASTER, independently of normalized IDs."""
import re

import pytest
from sqlalchemy import delete, select, update

from test_management import rental_tables


PATH = "/api/v1/organizations/spots"
ORG = "normalized-root-org"
REGION = "normalized-region"
LOCAL = "normalized-local"
LEAF = "normalized-existing-spot"
REGION_MASTER = "master-region"
LOCAL_MASTER = "master-local"
SIBLING_MASTER = "master-sibling-region"
RESPONSE_FIELDS = {"spot_id", "unit_code", "spot_name", "hierarchy_level", "phone", "biz_reg_num",
    "address", "zip_code", "lat", "lng", "contract_start", "contract_end", "is_active", "inviteCode",
    "email", "parentSpotMasterId"}


@pytest.fixture
def distinct_ids(setup, rental_tables):
    db, engine = setup["db"], setup["engine"]
    master, rent, org = (db.table(name) for name in ("MSP_SPOT_MASTER", "MSP_SPOT_RENT", "MSP_ORG"))
    with engine.begin() as connection:
        # Keep every fixture descendant on its real normalized organization,
        # while administrator membership and scope continue to use Master IDs.
        for old, normalized in (("root", ORG), ("foreign", "normalized-foreign-org"),
                                ("sibling", "normalized-other-org")):
            connection.execute(update(org).where(org.c.org_id == old).values(org_id=normalized))
            connection.execute(update(master).where(master.c.org_id == old).values(org_id=normalized))
            for name in ("MSP_REGION", "MSP_LOCAL", "MSP_SPOT"):
                table = db.table(name)
                connection.execute(update(table).where(table.c.org_id == old).values(org_id=normalized))
        connection.execute(update(master).where(master.c.hierarchy_level != "spot").values(spot_name=None))
        root = dict(connection.execute(select(master).where(master.c.spot_master_id == "root")).mappings().one())

        def add_level(ident, normalized, level, name, code, *, region_id=None, local_id=None):
            row = {**root, "spot_master_id": ident, "unit_code": code, "unit_name": name,
                "spot_name": None, "hierarchy_level": level, "region_id": region_id,
                "local_id": local_id, "spot_id": None,
                "region_name": "Existing region" if region_id == REGION else name,
                "local_name": name if level == "local" else None}
            row[level + "_id"] = normalized
            connection.execute(master.insert().values(**row))
            table = db.table("MSP_" + level.upper())
            values = {key: value for key, value in row.items() if key in table.c}
            values[level + "_name"] = name
            connection.execute(table.insert().values(**values))
            connection.execute(rent.insert().values(spot_master_id=ident, invite_code="fixture-" + ident,
                delivery_service_type="NONE"))

        add_level(REGION_MASTER, REGION, "region", "Existing region", root["unit_code"] + "-R01")
        add_level(LOCAL_MASTER, LOCAL, "local", "Existing local", root["unit_code"] + "-R01-L01", region_id=REGION)
        add_level(SIBLING_MASTER, "normalized-sibling-region", "region", "Sibling region", root["unit_code"] + "-R02")

        child_code = root["unit_code"] + "-R01-L01-SP01"
        connection.execute(update(master).where(master.c.spot_master_id == "child").values(
            region_id=REGION, local_id=LOCAL, spot_id=LEAF, unit_code=child_code,
            region_name="Existing region", local_name="Existing local"))
        spot = db.table("MSP_SPOT")
        connection.execute(update(spot).where(spot.c.spot_id == "child").values(
            spot_id=LEAF, org_id=ORG, region_id=REGION, local_id=LOCAL, unit_code=child_code))
        for level, suffix in (("team", "T01"), ("agency", "A01")):
            ident = "legacy-" + level + "-master"
            connection.execute(master.insert().values(**{**root, "spot_master_id": ident,
                "unit_code": root["unit_code"] + "-" + suffix, "spot_name": None,
                "unit_name": "Legacy " + level, "hierarchy_level": level, "spot_id": None}))
            connection.execute(rent.insert().values(spot_master_id=ident, invite_code="fixture-" + level,
                delivery_service_type="NONE"))
    return setup


def body(parent, level, name="Created through Master ID"):
    return {"parent_spot_id": parent, "unit_type": level, "spot_name": name,
        "email": "isolated-branch@example.com", "address": "Isolated branch entrance",
        "lat": -8.65, "lng": 115.2}


def snapshot(ctx):
    with ctx["engine"].connect() as connection:
        return {name: [dict(row) for row in connection.execute(select(ctx["db"].table(name))).mappings()]
            for name in ("MSP_SPOT_MASTER", "MSP_SPOT_RENT", "MSP_ORG", "MSP_REGION", "MSP_LOCAL", "MSP_SPOT")}


@pytest.mark.parametrize("parent,level,prefix,ancestors", [
    ("root", "region", "R", {"org_id": ORG}),
    (REGION_MASTER, "local", "L", {"org_id": ORG, "region_id": REGION}),
    (LOCAL_MASTER, "spot", "SP", {"org_id": ORG, "region_id": REGION, "local_id": LOCAL}),
])
@pytest.mark.parametrize("hint", ["region", "local", "spot", "team", "agency"])
def test_parent_master_id_creates_each_level_and_inherits_normalized_ancestors(
        distinct_ids, signin, parent, level, prefix, ancestors, hint):
    ctx, headers = distinct_ids, signin()
    master = ctx["db"].table("MSP_SPOT_MASTER")
    with ctx["engine"].connect() as connection:
        original_parent = connection.execute(select(master).where(master.c.spot_master_id == parent)).mappings().one()
        assert original_parent["spot_id"] is None
        assert original_parent["spot_name"] is None and original_parent["unit_name"]
        assert original_parent[original_parent["hierarchy_level"] + "_id"] != parent

    response = ctx["client"].post(PATH, headers=headers, json=body(parent, hint))

    assert response.status_code == 200, response.text
    created = response.json()
    assert set(created) == RESPONSE_FIELDS
    assert created["parentSpotMasterId"] == parent
    assert created["hierarchy_level"] == level and created["is_active"] is True
    assert created["spot_name"] == "Created through Master ID"
    assert re.fullmatch(re.escape(original_parent["unit_code"]) + "-" + prefix + r"\d+", created["unit_code"])
    assert re.fullmatch(r"[A-Z0-9]{8}", created["inviteCode"])
    with ctx["engine"].connect() as connection:
        stored = connection.execute(select(master).where(master.c.spot_master_id == created["spot_id"])).mappings().one()
        assert stored["spot_master_id"] == created["spot_id"]
        assert stored["contract_id"] == "CT1"
        assert stored["unit_name"] == "Created through Master ID"
        assert stored["spot_name"] == ("Created through Master ID" if level == "spot" else None)
        for column, expected in ancestors.items():
            assert stored[column] == expected
        if level != "spot":
            # The public spot_id is the new Master ID even for non-leaf nodes.
            assert stored["spot_id"] is None and created["spot_id"] is not None
        normal = ctx["db"].table("MSP_" + level.upper())
        normalized = connection.execute(select(normal).where(
            normal.c[level + "_id"] == stored[level + "_id"])).mappings().one()
        assert normalized["unit_code"] == stored["unit_code"]
        for column, expected in ancestors.items():
            assert normalized[column] == expected
        rent = ctx["db"].table("MSP_SPOT_RENT")
        assert connection.scalar(select(rent.c.invite_code).where(
            rent.c.spot_master_id == created["spot_id"])) == created["inviteCode"]
    hierarchy = ctx["client"].get(PATH + "/hierarchy", headers=headers)
    assert hierarchy.status_code == 200, hierarchy.text
    assert hierarchy.json()["currentSpotMasterId"] == "root" and hierarchy.json()["companyId"] == ORG
    entry = next(item for item in hierarchy.json()["items"] if item["spot_master_id"] == created["spot_id"])
    assert entry["parentSpotMasterId"] == parent
    assert entry["spot_name"] == "Created through Master ID"
    assert entry["canCreateChild"] is (level in ("region", "local"))


@pytest.mark.parametrize("normalized_parent,level", [
    (ORG, "region"), (REGION, "local"), (LOCAL, "spot"), (LEAF, "spot"),
])
def test_normalized_parent_ids_are_not_promoted_or_used_as_lookup_fallback(distinct_ids, signin, normalized_parent, level):
    ctx, headers = distinct_ids, signin()
    before = snapshot(ctx)

    response = ctx["client"].post(PATH, headers=headers, json=body(normalized_parent, level))

    assert response.status_code == 404 and response.json()["errorCode"] == "PARENT_SPOT_NOT_FOUND"
    assert snapshot(ctx) == before


@pytest.mark.parametrize("parent", ["child", "legacy-team-master", "legacy-agency-master"])
def test_leaf_and_unsupported_parent_levels_cannot_create_children(distinct_ids, signin, parent):
    ctx, headers = distinct_ids, signin()
    before = snapshot(ctx)

    response = ctx["client"].post(PATH, headers=headers, json=body(parent, "spot"))

    assert response.status_code == 422 and response.json()["errorCode"] == "CHILD_HIERARCHY_NOT_SUPPORTED"
    assert snapshot(ctx) == before


@pytest.mark.parametrize("actor", ["primary", "general"])
def test_hierarchy_child_creation_flags_match_supported_parent_levels(distinct_ids, signin, actor):
    response = distinct_ids["client"].get(PATH + "/hierarchy", headers=signin(actor))

    assert response.status_code == 200, response.text
    entries = {item["spot_master_id"]: item for item in response.json()["items"]}
    for ident in (REGION_MASTER, LOCAL_MASTER, SIBLING_MASTER):
        assert entries[ident]["canCreateChild"] is (actor == "primary")
    for ident in ("child", "legacy-team-master", "legacy-agency-master"):
        assert entries[ident]["canCreateChild"] is False


def test_legacy_spot_hint_walks_region_local_spot_and_reserves_existing_region_sequence(distinct_ids, signin):
    ctx, headers = distinct_ids, signin()
    with ctx["engine"].begin() as connection:
        rent, master, region = (ctx["db"].table(name) for name in ("MSP_SPOT_RENT", "MSP_SPOT_MASTER", "MSP_REGION"))
        connection.execute(delete(rent).where(rent.c.spot_master_id == SIBLING_MASTER))
        connection.execute(delete(master).where(master.c.spot_master_id == SIBLING_MASTER))
        connection.execute(delete(region).where(region.c.region_id == "normalized-sibling-region"))
    parent, prefix = "root", "CT1-ORG01"
    ancestors = {"org_id": ORG}
    for level, suffix, name in (("region", "R02", "Next region"), ("local", "L01", "Next local"),
                                ("spot", "SP01", "Next spot")):
        response = ctx["client"].post(PATH, headers=headers, json=body(parent, "spot", name))
        assert response.status_code == 200, response.text
        created = response.json()
        prefix += "-" + suffix
        assert created["hierarchy_level"] == level and created["unit_code"] == prefix
        assert created["parentSpotMasterId"] == parent
        with ctx["engine"].connect() as connection:
            master = ctx["db"].table("MSP_SPOT_MASTER")
            stored = connection.execute(select(master).where(master.c.spot_master_id == created["spot_id"])).mappings().one()
            normal = ctx["db"].table("MSP_" + level.upper())
            normalized = connection.execute(select(normal).where(normal.c[level + "_id"] == stored[level + "_id"])).mappings().one()
            assert stored["unit_name"] == normalized[level + "_name"] == name
            assert stored["spot_name"] == (name if level == "spot" else None)
            for column, expected in ancestors.items():
                assert stored[column] == normalized[column] == expected
            ancestors[level + "_id"] = stored[level + "_id"]
        parent = created["spot_id"]
    before = snapshot(ctx)
    blocked = ctx["client"].post(PATH, headers=headers, json=body(parent, "spot", "No level after spot"))
    assert blocked.status_code == 422 and blocked.json()["errorCode"] == "CHILD_HIERARCHY_NOT_SUPPORTED"
    assert snapshot(ctx) == before


@pytest.mark.parametrize("parent,column", [
    (REGION_MASTER, "region_id"), (LOCAL_MASTER, "region_id"), (LOCAL_MASTER, "local_id"),
])
def test_missing_normalized_ancestor_is_rejected_even_when_column_is_nullable(distinct_ids, signin, parent, column):
    ctx, headers = distinct_ids, signin()
    table = ctx["db"].table("MSP_SPOT_MASTER")
    with ctx["engine"].begin() as connection:
        assert table.c[column].nullable
        connection.execute(update(table).where(table.c.spot_master_id == parent).values(**{column: None}))
    before = snapshot(ctx)

    response = ctx["client"].post(PATH, headers=headers, json=body(parent, "spot"))

    assert response.status_code == 422 and response.json()["errorCode"] == "PARENT_HIERARCHY_INCOMPLETE"
    assert snapshot(ctx) == before


@pytest.mark.parametrize("master_id", ["root", REGION_MASTER, LOCAL_MASTER, "child"])
def test_admin_location_identifier_stays_master_id_after_login_and_profile_update(distinct_ids, master_id):
    ctx = distinct_ids
    admins, scopes = (ctx["db"].table(name) for name in ("MSP_ADMIN", "MSP_ADMIN_SPOT_SCOPE"))
    with ctx["engine"].begin() as connection:
        connection.execute(update(admins).where(admins.c.admin_id == "primary").values(primary_spot_master_id=master_id))
        connection.execute(update(scopes).where(scopes.c.admin_id == "primary",
            scopes.c.spot_master_id == "root").values(spot_master_id=master_id))
        master = ctx["db"].table("MSP_SPOT_MASTER")
        location = connection.execute(select(master).where(master.c.spot_master_id == master_id)).mappings().one()
        normalized_id = location[location["hierarchy_level"] + "_id"]
        assert normalized_id != master_id
    credentials = {"email": "primary@example.com", "password": "Test-password-123!"}

    login = ctx["client"].post("/nadreego/admin/login", json=credentials)

    assert login.status_code == 200, login.text
    assert login.json()["admin"]["spotMasterId"] == master_id
    headers = {"Authorization": "Bearer " + login.json()["accessToken"], "X-Refresh-Token": login.json()["refreshToken"]}
    updated = ctx["client"].post("/nadreego/admin/update", headers=headers, json={"name": "Updated isolated representative"})
    assert updated.status_code == 200, updated.text
    assert updated.json() == {"status": "success", "adminId": "primary", "name": "Updated isolated representative",
        "email": "primary@example.com"}
    with ctx["engine"].connect() as connection:
        assert connection.scalar(select(admins.c.primary_spot_master_id).where(admins.c.admin_id == "primary")) == master_id
    repeated = ctx["client"].post("/nadreego/admin/login", json=credentials)
    assert repeated.status_code == 200 and repeated.json()["admin"]["spotMasterId"] == master_id


def test_parent_master_from_another_contract_remains_inaccessible(distinct_ids, signin):
    ctx, headers = distinct_ids, signin()
    before = snapshot(ctx)

    response = ctx["client"].post(PATH, headers=headers, json=body("foreign", "region"))

    assert response.status_code == 404 and response.json()["errorCode"] == "PARENT_SPOT_NOT_FOUND"
    assert snapshot(ctx) == before


def test_branch_representative_cannot_create_under_sibling_master_in_same_company(distinct_ids, signin):
    ctx = distinct_ids
    admins, scopes = (ctx["db"].table(name) for name in ("MSP_ADMIN", "MSP_ADMIN_SPOT_SCOPE"))
    with ctx["engine"].begin() as connection:
        connection.execute(update(admins).where(admins.c.admin_id == "primary").values(primary_spot_master_id=REGION_MASTER))
        connection.execute(update(scopes).where(scopes.c.admin_id == "primary",
            scopes.c.spot_master_id == "root").values(spot_master_id=REGION_MASTER))
    headers = signin()
    allowed = ctx["client"].post(PATH, headers=headers,
        json=body(REGION_MASTER, "local", "Allowed direct descendant"))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["parentSpotMasterId"] == REGION_MASTER
    before = snapshot(ctx)

    response = ctx["client"].post(PATH, headers=headers, json=body(SIBLING_MASTER, "local", "Forbidden sibling child"))

    assert response.status_code == 404 and response.json()["errorCode"] == "PARENT_SPOT_NOT_FOUND"
    assert snapshot(ctx) == before


@pytest.mark.parametrize("parent", ["root", REGION_MASTER])
def test_non_leaf_duplicate_name_uses_unit_name_when_spot_name_is_null(distinct_ids, signin, parent):
    ctx, headers = distinct_ids, signin()
    created = ctx["client"].post(PATH, headers=headers, json=body(parent, "spot", "Unique own unit name"))
    assert created.status_code == 200, created.text
    master = ctx["db"].table("MSP_SPOT_MASTER")
    with ctx["engine"].connect() as connection:
        stored = connection.execute(select(master).where(master.c.spot_master_id == created.json()["spot_id"])).mappings().one()
        assert stored["unit_name"] == "Unique own unit name" and stored["spot_name"] is None
    before = snapshot(ctx)

    repeated = ctx["client"].post(PATH, headers=headers, json=body(parent, "agency", "Unique own unit name"))

    assert repeated.status_code == 409 and repeated.json()["errorCode"] == "DUPLICATE_SPOT_NAME"
    assert snapshot(ctx) == before


@pytest.mark.parametrize("target,level", [
    ("root", "org"), (REGION_MASTER, "region"), (LOCAL_MASTER, "local"), ("child", "spot"),
])
def test_branch_rename_updates_own_unit_name_normalized_name_and_only_matching_ancestor_caches(distinct_ids, signin, target, level):
    ctx, headers = distinct_ids, signin()
    before = {row["spot_master_id"]: row for row in snapshot(ctx)["MSP_SPOT_MASTER"]}
    own = before[target]
    renamed = "Renamed own " + level

    response = ctx["client"].post("/nadreego/shop/update", headers=headers,
        json={"spotMasterId": target, "shopName": renamed})

    assert response.status_code == 200, response.text
    after = {row["spot_master_id"]: row for row in snapshot(ctx)["MSP_SPOT_MASTER"]}
    assert after[target]["unit_name"] == renamed
    assert after[target]["spot_name"] == (renamed if level == "spot" else None)
    with ctx["engine"].connect() as connection:
        normal = ctx["db"].table("MSP_" + level.upper())
        assert connection.scalar(select(normal.c[level + "_name"]).where(
            normal.c[level + "_id"] == own[level + "_id"])) == renamed
    for ident, previous in before.items():
        current = after[ident]
        if ident != target:
            assert current["unit_name"] == previous["unit_name"]
            assert current["spot_name"] == previous["spot_name"]
        for cache in ("org_name", "region_name", "local_name"):
            affected = (cache == level + "_name" and previous.get(level + "_id") == own.get(level + "_id")
                and previous["org_id"] == own["org_id"] and previous["contract_id"] == own["contract_id"])
            assert current[cache] == (renamed if affected else previous[cache])
    profile = ctx["client"].get("/nadreego/shop/profile", headers=headers, params={"spotMasterId": target})
    assert profile.status_code == 200 and profile.json()["shopName"] == renamed
    searched = ctx["client"].get(PATH + "/hierarchy", headers=headers, params={"search": renamed})
    assert searched.status_code == 200, searched.text
    expected = [] if target == "root" else [target]
    assert [row["spot_master_id"] for row in searched.json()["items"]] == expected
    assert all(row["spot_name"] == renamed for row in searched.json()["items"])
