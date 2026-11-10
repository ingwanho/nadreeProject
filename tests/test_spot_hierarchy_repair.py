"""Pure snapshot tests; no shared database or service configuration is used."""
from copy import deepcopy
from datetime import date
from uuid import UUID

import pytest

from app.spot_hierarchy_repair import plan_repair


TABLES = (
    "MSP_SPOT_MASTER", "MSP_ORG", "MSP_REGION", "MSP_LOCAL", "MSP_SPOT",
    "MSP_ADMIN_SPOT_SCOPE",
)
LEVELS = ("org", "region", "local", "spot")


def snapshot():
    return {table: [] for table in TABLES}


def profile():
    return {
        "address": "Synthetic test premises", "phone": "0000000000",
        "biz_reg_num": "TEST-ONLY", "zip_code": "00000", "lat": -8.0,
        "lng": 115.0, "contract_start": date(2026, 1, 1),
        "contract_end": date(2027, 1, 1), "is_active": 1,
    }


def normal(level, ident, code, *, name=None, org_id="normal-org", region_id=None, local_id=None):
    row = {
        **profile(), level + "_id": ident,
        level + "_name": name or "Test " + level,
        "contract_id": "TEST-CONTRACT", "unit_code": code,
    }
    ancestors = {"org_id": org_id, "region_id": region_id, "local_id": local_id}
    row.update({key: value for key, value in ancestors.items()
                if LEVELS.index(key[:-3]) < LEVELS.index(level)})
    return row


def master(ident, code, level, *, name=None, org_id="normal-org", region_id=None,
           local_id=None, spot_id=None, org_name="Current organization",
           region_name=None, local_name=None):
    own_name = name or "Test " + str(level)
    return {
        **profile(), "spot_master_id": ident, "contract_id": "TEST-CONTRACT",
        "org_id": org_id, "region_id": region_id, "local_id": local_id,
        "spot_id": spot_id, "unit_code": code,
        "unit_name": own_name,
        "spot_name": own_name if level in ("spot", None) else None, "hierarchy_level": level,
        "org_name": org_name, "region_name": region_name, "local_name": local_name,
    }


def with_org():
    data = snapshot()
    data["MSP_ORG"].append(normal("org", "normal-org", "ORG01", name="Old organization"))
    data["MSP_SPOT_MASTER"].append(master(
        "master-org", "ORG01", "org", name="Current organization"))
    return data


def direct_spots():
    data = with_org()
    for number in (1, 2):
        code = f"ORG01-SP{number:02d}"
        name = f"Current branch {number}"
        data["MSP_SPOT_MASTER"].append(master(
            f"master-branch-{number}", code, "spot", name=name,
            spot_id=f"normal-spot-{number}",
        ))
        data["MSP_SPOT"].append(normal(
            "spot", f"normal-spot-{number}", code, name=name,
        ))
    data["MSP_ADMIN_SPOT_SCOPE"] = [
        {"id": 1, "admin_id": "synthetic-admin-1", "spot_master_id": "master-branch-1",
         "spot_id": "normal-spot-1", "unit_code": "ORG01-SP01", "access_type": "manage"},
        {"id": 2, "admin_id": "synthetic-admin-2", "spot_master_id": "master-branch-1",
         "spot_id": "normal-spot-1", "unit_code": "STALE-CODE", "access_type": "manage"},
        {"id": 3, "admin_id": "synthetic-admin-3", "spot_master_id": "master-org",
         "spot_id": None, "unit_code": "ORG01-SP01", "access_type": "manage"},
        {"id": 4, "admin_id": "synthetic-admin-4", "spot_master_id": None,
         "spot_id": "normal-spot-1", "unit_code": "ORG01-SP01", "access_type": "manage"},
    ]
    return data


def legacy_chain():
    data = snapshot()
    data["MSP_ORG"].append(normal("org", "normal-org", "ORG01", name="Test organization"))
    data["MSP_REGION"].append(normal(
        "region", "normal-region", "ORG01-RG01", name="Test region"))
    data["MSP_LOCAL"].append(normal(
        "local", "normal-local", "ORG01-RG01-LO001", name="Test locality",
        region_id="normal-region"))
    data["MSP_SPOT"].append(normal(
        "spot", "normal-spot", "ORG01-RG01-LO001-SP001", name="Old branch name",
        region_id="normal-region", local_id="normal-local"))
    data["MSP_SPOT_MASTER"].append(master(
        "existing-leaf-master", "ORG01-RG01-LO001-SP001", None,
        name="Current branch name", region_id="normal-region", local_id="normal-local",
        spot_id="normal-spot", org_name="Test organization",
        region_name="Test region", local_name="Test locality"))
    data["MSP_SPOT_MASTER"][0]["spot_name"] = "Stale branch cache"
    return data


def row(data, table, **key):
    found = [item for item in data[table]
             if all(item.get(name) == value for name, value in key.items())]
    assert len(found) == 1, (table, key)
    return found[0]


def apply_plan(data, plan):
    """Apply only the documented insert/update representation to a copy."""
    operations, problems = plan
    assert not problems
    result = deepcopy(data)
    updated_keys = set()
    for operation in operations:
        assert set(operation) >= {"table", "key", "before", "values"}
        assert operation["table"] in TABLES
        target = (operation["table"], tuple(sorted(operation["key"].items())))
        assert target not in updated_keys
        updated_keys.add(target)
        table = result[operation["table"]]
        matches = [item for item in table
                   if all(item.get(name) == value for name, value in operation["key"].items())]
        if operation["before"] is None:
            assert not matches
            assert all(operation["values"].get(name) == value
                       for name, value in operation["key"].items())
            table.append(deepcopy(operation["values"]))
        else:
            assert len(matches) == 1
            assert matches[0] == operation["before"]
            matches[0].update(deepcopy(operation["values"]))
    return result


def test_direct_org_spots_become_regions_without_replacing_master_or_historical_ids():
    data = direct_spots()
    data["MSP_RENTAL_CONTRACT"] = [{
        "rental_contract_id": "synthetic-history", "pickup_spot_master_id": "master-branch-1",
        "vehicle_id": "synthetic-vehicle", "contract_status": "RETURNED",
    }]
    before = deepcopy(data)
    result = apply_plan(data, plan_repair(data))

    for number in (1, 2):
        current = row(result, "MSP_SPOT_MASTER", spot_master_id=f"master-branch-{number}")
        previous = row(before, "MSP_SPOT_MASTER", spot_master_id=f"master-branch-{number}")
        assert current["hierarchy_level"] == "region"
        assert current["unit_code"] == f"ORG01-R{number:02d}"
        assert current["spot_id"] is None and current["local_id"] is None
        assert current["region_id"]
        for name in profile():
            assert current[name] == previous[name]
        assert current["unit_name"] == previous["unit_name"]
        assert current["spot_name"] is None
        old_normal = row(result, "MSP_SPOT", spot_id=f"normal-spot-{number}")
        assert old_normal == {**row(before, "MSP_SPOT", spot_id=f"normal-spot-{number}"), "is_active": 0}
        region = row(result, "MSP_REGION", region_id=current["region_id"])
        assert region["unit_code"] == current["unit_code"]
        assert region["region_name"] == current["unit_name"]
        assert region["org_id"] == "normal-org"
    assert result["MSP_RENTAL_CONTRACT"] == before["MSP_RENTAL_CONTRACT"]


def test_reclassification_updates_scope_code_only_for_matching_master_and_old_code():
    data = direct_spots()
    result = apply_plan(data, plan_repair(data))
    converted = row(result, "MSP_SPOT_MASTER", spot_master_id="master-branch-1")
    assert row(result, "MSP_ADMIN_SPOT_SCOPE", id=1) == {
        **row(data, "MSP_ADMIN_SPOT_SCOPE", id=1), "unit_code": converted["unit_code"]}
    for ident in (2, 3, 4):
        assert row(result, "MSP_ADMIN_SPOT_SCOPE", id=ident) == row(data, "MSP_ADMIN_SPOT_SCOPE", id=ident)


def test_region_code_allocation_avoids_both_master_and_normalized_region_codes():
    data = direct_spots()
    data["MSP_REGION"].extend([
        normal("region", "occupied-region-1", "ORG01-R01", name="Occupied region one"),
        normal("region", "occupied-region-2", "ORG01-R02", name="Occupied region two"),
    ])
    data["MSP_SPOT_MASTER"].append(master(
        "occupied-master", "ORG01-R01", "region", name="Occupied region one",
        region_id="occupied-region-1", region_name="Occupied region one"))
    result = apply_plan(data, plan_repair(data))
    allocated = {row(result, "MSP_SPOT_MASTER", spot_master_id=f"master-branch-{number}")["unit_code"]
                 for number in (1, 2)}
    assert allocated == {"ORG01-R03", "ORG01-R04"}
    assert row(result, "MSP_REGION", region_id="occupied-region-1")["unit_code"] == "ORG01-R01"
    assert row(result, "MSP_REGION", region_id="occupied-region-2")["unit_code"] == "ORG01-R02"
    assert len({item["unit_code"] for item in result["MSP_SPOT_MASTER"]}) == len(result["MSP_SPOT_MASTER"])


def test_missing_legacy_ancestor_masters_are_created_with_distinct_deterministic_uuid5_ids():
    data = legacy_chain()
    plan = plan_repair(data)
    assert plan == plan_repair(deepcopy(data))
    result = apply_plan(data, plan)
    inserts = [operation for operation in plan[0]
               if operation["table"] == "MSP_SPOT_MASTER" and operation["before"] is None]
    assert len(inserts) == 3
    assert {operation["values"]["hierarchy_level"] for operation in inserts} == {"org", "region", "local"}
    normal_ids = {"normal-org", "normal-region", "normal-local", "normal-spot"}
    inserted_ids = {operation["values"]["spot_master_id"] for operation in inserts}
    assert len(inserted_ids) == 3 and not inserted_ids & normal_ids
    assert all(UUID(ident).version == 5 for ident in inserted_ids)
    for level, code, ident in (
        ("org", "ORG01", "normal-org"),
        ("region", "ORG01-RG01", "normal-region"),
        ("local", "ORG01-RG01-LO001", "normal-local"),
    ):
        ancestor = row(result, "MSP_SPOT_MASTER", hierarchy_level=level)
        assert ancestor["unit_code"] == code
        assert ancestor[level + "_id"] == ident
    leaf = row(result, "MSP_SPOT_MASTER", spot_master_id="existing-leaf-master")
    assert leaf["hierarchy_level"] == "spot"
    assert leaf["unit_code"] == "ORG01-RG01-LO001-SP001"
    assert leaf["spot_id"] == "normal-spot"
    assert leaf["unit_name"] == "Current branch name"
    assert leaf["spot_name"] == "Current branch name"
    assert row(result, "MSP_SPOT", spot_id="normal-spot")["spot_name"] == "Current branch name"


def test_name_caches_prefer_current_master_name_and_clear_absent_lower_levels():
    data = with_org()
    root = data["MSP_SPOT_MASTER"][0]
    root.update(region_name="Stale region", local_name="Stale locality")
    data["MSP_REGION"].append(normal("region", "normal-region", "ORG01-RG01", name="Old region"))
    data["MSP_SPOT_MASTER"].append(master(
        "master-region", "ORG01-RG01", "region", name="Current region",
        region_id="normal-region", org_name="Old organization",
        region_name="Old region", local_name="Stale locality"))
    data["MSP_LOCAL"].append(normal(
        "local", "normal-local", "ORG01-RG01-LO001", name="Old locality",
        region_id="normal-region"))
    data["MSP_SPOT_MASTER"].append(master(
        "master-local", "ORG01-RG01-LO001", "local", name="Current locality",
        region_id="normal-region", local_id="normal-local", org_name="Old organization",
        region_name="Old region", local_name="Old locality"))
    result = apply_plan(data, plan_repair(data))
    repaired_org = row(result, "MSP_SPOT_MASTER", spot_master_id="master-org")
    repaired_region = row(result, "MSP_SPOT_MASTER", spot_master_id="master-region")
    repaired_local = row(result, "MSP_SPOT_MASTER", spot_master_id="master-local")
    assert repaired_org["org_name"] == "Current organization"
    assert repaired_org["spot_name"] is None
    assert repaired_org["region_name"] is None and repaired_org["local_name"] is None
    assert row(result, "MSP_ORG", org_id="normal-org")["org_name"] == repaired_org["unit_name"]
    assert repaired_region["org_name"] == "Current organization"
    assert repaired_region["region_name"] == "Current region"
    assert repaired_region["spot_name"] is None
    assert repaired_region["local_name"] is None
    assert row(result, "MSP_REGION", region_id="normal-region")["region_name"] == repaired_region["unit_name"]
    assert repaired_local["org_name"] == "Current organization"
    assert repaired_local["region_name"] == "Current region"
    assert repaired_local["local_name"] == "Current locality"
    assert repaired_local["spot_name"] is None
    assert row(result, "MSP_LOCAL", local_id="normal-local")["local_name"] == repaired_local["unit_name"]


@pytest.mark.parametrize("current_name", [None, ""])
def test_empty_current_master_name_is_not_restored_from_old_normalized_name(current_name):
    data = with_org()
    data["MSP_SPOT_MASTER"][0].update(
        unit_name=current_name, org_name="Old organization")
    data["MSP_REGION"].append(normal(
        "region", "normal-region", "ORG01-RG01", name="Current region"))
    data["MSP_SPOT_MASTER"].append(master(
        "master-region", "ORG01-RG01", "region", name="Current region",
        region_id="normal-region", org_name="Old organization", region_name="Current region"))
    result = apply_plan(data, plan_repair(data))
    repaired_org = row(result, "MSP_SPOT_MASTER", spot_master_id="master-org")
    repaired_region = row(result, "MSP_SPOT_MASTER", spot_master_id="master-region")
    assert repaired_org["unit_name"] == current_name
    assert repaired_org["spot_name"] is None
    assert repaired_org["org_name"] in (None, "")
    assert repaired_region["org_name"] in (None, "")
    assert row(result, "MSP_ORG", org_id="normal-org")["org_name"] in (None, "")


@pytest.mark.parametrize("builder", [direct_spots, legacy_chain])
def test_repair_is_pure_and_applied_plan_is_idempotent(builder):
    data = builder()
    original = deepcopy(data)
    plan = plan_repair(data)
    assert data == original
    applied = apply_plan(data, plan)
    operations, problems = plan_repair(applied)
    assert problems == []
    assert operations == []
    assert data == original


@pytest.mark.parametrize("failure", ["missing_ancestor", "ambiguous_parent", "duplicate_id", "duplicate_code"])
def test_unsafe_snapshot_produces_diagnostics_without_partial_operations(failure):
    data = legacy_chain()
    if failure == "missing_ancestor":
        data["MSP_REGION"] = []
    elif failure == "ambiguous_parent":
        data["MSP_SPOT_MASTER"].extend([
            master("ambiguous-org-one", "ORG01", "org", name="Organization one"),
            master("ambiguous-org-two", "ORG02", "org", name="Organization two"),
        ])
    elif failure == "duplicate_id":
        duplicate = deepcopy(data["MSP_SPOT_MASTER"][0])
        duplicate["unit_code"] = "OTHER-CODE"
        data["MSP_SPOT_MASTER"].append(duplicate)
    else:
        duplicate = deepcopy(data["MSP_SPOT_MASTER"][0])
        duplicate["spot_master_id"] = "another-master-with-same-code"
        data["MSP_SPOT_MASTER"].append(duplicate)
    original = deepcopy(data)
    operations, problems = plan_repair(data)
    assert problems
    assert operations == []
    assert data == original
