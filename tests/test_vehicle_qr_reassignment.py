"""Releasing a QR preserves its audit history while allowing later assignment."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.receipt import hold_reason
from app.rental_schema import metadata
from app.security import now
from test_vehicle_qr import equipment, lookup, register


LINK = "/nadreego/vehicle/qr/link"
DELETE = "/nadreego/sensor/delete"
ORIGINAL = "NDR-Ab12Cd34"


def detach(client, headers, plate):
    return client.post(DELETE, headers=headers, json={"vehicleNumber": plate, "division": "QR"})


def link(client, headers, plate, token=ORIGINAL):
    return client.post(LINK, headers=headers, json={"vehicleNumber": plate, "qrToken": token})


def table_rows(setup, name):
    with setup["engine"].connect() as connection:
        return [dict(row) for row in connection.execute(select(setup["db"].table(name))).mappings()]


def qr_rows(setup):
    return table_rows(setup, "MSP_VEHICLE_QR"), table_rows(setup, "MSP_VEHICLE_QR_HISTORY")


def create(client, headers, *, plate="QR-OLD", token=ORIGINAL, sensor=False):
    response = register(client, headers, qr=token, plate=plate, sensor=sensor)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("status", ["ACTIVE", "INACTIVE", "EXPIRED"])
def test_delete_removes_only_current_qr_and_preserves_deleted_history_and_sensor(client, signin, setup, equipment, status):
    headers = signin()
    created = create(client, headers, sensor=True)
    with setup["engine"].begin() as connection:
        qr = metadata.tables["MSP_VEHICLE_QR"]
        connection.execute(qr.update().where(qr.c.vehicle_id == created["vehicleId"]).values(qr_status=status))
    current, issued = qr_rows(setup)
    business = {name: table_rows(setup, name) for name in (
        "MSP_VEHICLE", "MSP_RENTAL_VEHICLE", "MSP_VEHICLE_STATUS", "MSP_VEHICLE_SPOT_HISTORY", "MSP_SENSOR")}
    listed = client.post("/nadreego/vehicle/select", headers=headers, json={"page": 1, "pageSize": 50})
    assert listed.status_code == 200, listed.text
    actions = next(item["availableActions"] for item in listed.json()["items"] if item["vehicle"]["vehicleId"] == created["vehicleId"])
    assert "QR_DELETE" in actions and "QR_LINK" not in actions

    removed = detach(client, headers, "QR-OLD")

    assert removed.status_code == 200 and removed.json()["status"] == "success"
    remaining, history = qr_rows(setup)
    assert remaining == []
    assert len(history) == len(issued) + 1
    assert history[0] == issued[0]
    deleted = next(row for row in history if row["change_type"] == "DELETED")
    assert deleted["vehicle_id"] == created["vehicleId"]
    assert deleted["qr_id"] == created["qr"]["qrId"] == current[0]["qr_id"]
    assert deleted["qr_code_hash"] == current[0]["qr_code_hash"]
    assert deleted["qr_status"] == "INACTIVE"
    assert deleted["changed_by"] == "primary"
    assert {name: table_rows(setup, name) for name in business} == business
    missing = lookup(client, headers, ORIGINAL)
    assert missing.status_code == 404 and missing.json()["errorCode"] == "QR_NOT_FOUND"
    listed = client.post("/nadreego/vehicle/select", headers=headers, json={"page": 1, "pageSize": 50})
    assert listed.status_code == 200, listed.text
    actions = next(item["availableActions"] for item in listed.json()["items"] if item["vehicle"]["vehicleId"] == created["vehicleId"])
    assert "QR_LINK" in actions and "QR_DELETE" not in actions
    repeated = detach(client, headers, "QR-OLD")
    assert repeated.status_code == 404 and repeated.json()["errorCode"] == "QR_NOT_FOUND"
    assert qr_rows(setup) == (remaining, history)


def test_released_qr_links_to_an_existing_vehicle_and_lookup_follows_new_owner(client, signin, setup, equipment):
    headers = signin()
    original = create(client, headers)
    target = create(client, headers, plate="QR-TARGET", token="NDR-Ef56Gh78")
    assert detach(client, headers, "QR-OLD").status_code == 200
    assert detach(client, headers, "QR-TARGET").status_code == 200
    _, before = qr_rows(setup)

    linked = link(client, headers, "QR-TARGET")

    assert linked.status_code == 200, linked.text
    assert linked.json() == {"status": "success", "vehicleId": target["vehicleId"],
        "qr": {"qrId": linked.json()["qr"]["qrId"], "qrStatus": "ACTIVE"}}
    assert linked.json()["qr"]["qrId"] != original["qr"]["qrId"]
    current, history = qr_rows(setup)
    assert len(current) == 1 and current[0]["vehicle_id"] == target["vehicleId"]
    assert current[0]["qr_id"] == linked.json()["qr"]["qrId"] and current[0]["qr_status"] == "ACTIVE"
    assert all(row in history for row in before)
    assert len(history) == len(before) + 1
    found = lookup(client, headers, ORIGINAL)
    assert found.status_code == 200, found.text
    assert found.json()["data"]["vehicleId"] == target["vehicleId"]
    assert found.json()["data"]["vehicle"]["vehicleNo"] == "QR-TARGET"
    assert found.json()["data"]["equipmentType"] == "QR_ONLY"
    assert lookup(client, headers, ORIGINAL.upper()).status_code == 404
    assert lookup(client, headers, "NDR-Ef56Gh78").status_code == 404


def test_released_qr_can_be_issued_again_to_its_original_vehicle(client, signin, setup, equipment):
    headers = signin()
    created = create(client, headers)
    assert detach(client, headers, "QR-OLD").status_code == 200

    restored = link(client, headers, "QR-OLD")

    assert restored.status_code == 200, restored.text
    assert restored.json()["vehicleId"] == created["vehicleId"]
    assert restored.json()["qr"]["qrId"] != created["qr"]["qrId"]
    assert lookup(client, headers, ORIGINAL).json()["data"]["vehicleId"] == created["vehicleId"]
    _, history = qr_rows(setup)
    assert len(history) == 3 and len([row for row in history if row["change_type"] == "DELETED"]) == 1


def test_vehicle_create_reuses_deleted_qr_but_still_rejects_current_duplicates(client, signin, setup, equipment):
    headers = signin()
    old = create(client, headers)
    assert detach(client, headers, "QR-OLD").status_code == 200

    new = create(client, headers, plate="QR-NEW")

    assert new["vehicleId"] != old["vehicleId"]
    assert lookup(client, headers, ORIGINAL).json()["data"]["vehicleId"] == new["vehicleId"]
    before = qr_rows(setup)
    vehicles = table_rows(setup, "MSP_VEHICLE")
    duplicate = register(client, headers, qr=ORIGINAL, plate="QR-DUPLICATE")
    assert duplicate.status_code == 409 and duplicate.json()["errorCode"] == "QR_ALREADY_ISSUED"
    assert qr_rows(setup) == before
    assert table_rows(setup, "MSP_VEHICLE") == vehicles
    assert any(row["change_type"] == "DELETED" and row["vehicle_id"] == old["vehicleId"] for row in before[1])


@pytest.mark.parametrize("actor", ["primary", "general"])
def test_link_same_active_qr_is_idempotent_without_duplicate_history(client, signin, setup, equipment, actor):
    created = create(client, signin())
    headers = signin(actor)
    before = qr_rows(setup)

    for _ in range(2):
        response = link(client, headers, "QR-OLD")
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "success", "vehicleId": created["vehicleId"],
            "qr": {"qrId": created["qr"]["qrId"], "qrStatus": "ACTIVE"}}
    assert qr_rows(setup) == before


def test_link_different_qr_cannot_replace_a_vehicle_current_assignment(client, signin, setup, equipment):
    headers = signin()
    create(client, headers)
    before = qr_rows(setup)

    response = link(client, headers, "QR-OLD", "NDR-Unused12")

    assert response.status_code == 409 and response.json()["errorCode"] == "VEHICLE_QR_ALREADY_LINKED"
    assert qr_rows(setup) == before


@pytest.mark.parametrize("owner,status", [
    ("another", "ACTIVE"), ("another", "INACTIVE"), ("another", "EXPIRED"),
    ("same", "INACTIVE"), ("same", "EXPIRED"), ("same", "ACTIVE_EXPIRED"),
])
def test_current_qr_occupancy_includes_inactive_and_expired_rows(client, signin, setup, equipment, owner, status):
    headers = signin()
    old = create(client, headers)
    target_plate = "QR-OLD"
    if owner == "another":
        create(client, headers, plate="QR-TARGET", token="NDR-Ef56Gh78")
        assert detach(client, headers, "QR-TARGET").status_code == 200
        target_plate = "QR-TARGET"
    with setup["engine"].begin() as connection:
        qr = metadata.tables["MSP_VEHICLE_QR"]
        values = {"qr_status": status}
        if status == "ACTIVE_EXPIRED":
            values = {"qr_status": "ACTIVE", "expired_at": now() - timedelta(seconds=1)}
        connection.execute(qr.update().where(qr.c.vehicle_id == old["vehicleId"]).values(**values))
    before = qr_rows(setup)

    response = link(client, headers, target_plate)

    assert response.status_code == 409 and response.json()["errorCode"] == "QR_ALREADY_ISSUED"
    assert qr_rows(setup) == before


@pytest.mark.parametrize("operation", ["delete", "link"])
@pytest.mark.parametrize("actor,expected", [(None, 401), ("outsider", 404)])
def test_qr_assignment_changes_require_auth_and_own_direct_branch(client, signin, setup, equipment, operation, actor, expected):
    primary = signin()
    create(client, primary)
    if operation == "link":
        assert detach(client, primary, "QR-OLD").status_code == 200
    before = qr_rows(setup)
    headers = {} if actor is None else signin(actor)

    response = detach(client, headers, "QR-OLD") if operation == "delete" else link(client, headers, "QR-OLD")

    assert response.status_code == expected, response.text
    assert qr_rows(setup) == before


@pytest.mark.parametrize("operation", ["delete", "link"])
def test_ancestor_representative_cannot_change_child_direct_branch_qr(client, signin, setup, equipment, operation):
    headers = signin()
    created = create(client, headers)
    if operation == "link":
        assert detach(client, headers, "QR-OLD").status_code == 200
    with setup["engine"].begin() as connection:
        history = equipment["MSP_VEHICLE_SPOT_HISTORY"]
        connection.execute(history.update().where(history.c.vehicle_id == created["vehicleId"]).values(spot_master_id="child"))
    before = qr_rows(setup)

    response = detach(client, headers, "QR-OLD") if operation == "delete" else link(client, headers, "QR-OLD")

    assert response.status_code == 404 and response.json()["errorCode"] == "VEHICLE_NOT_FOUND"
    assert qr_rows(setup) == before


def test_general_admin_keeps_same_branch_link_and_delete_permissions(client, signin, setup, equipment):
    primary = signin()
    create(client, primary)
    assert detach(client, primary, "QR-OLD").status_code == 200
    general = signin("general")

    linked = link(client, general, "QR-OLD")

    assert linked.status_code == 200, linked.text
    assert lookup(client, general, ORIGINAL).status_code == 200
    assert detach(client, general, "QR-OLD").status_code == 200
    current, history = qr_rows(setup)
    assert current == []
    assert len([row for row in history if row["change_type"] == "DELETED" and row["changed_by"] == "general"]) == 1


@pytest.mark.parametrize("operation", ["delete", "link", "repeat_active"])
@pytest.mark.parametrize("protection", ["ON_RENT", "OVERDUE", "HANDOVER_PENDING", "EXPIRED_RECEIPT_HOLD"])
def test_qr_changes_preserve_open_rentals_and_unreceived_vehicle_protection(client, signin, setup, equipment, operation, protection):
    headers = signin()
    created = create(client, headers)
    if operation == "link":
        assert detach(client, headers, "QR-OLD").status_code == 200
    ident, at = created["vehicleId"], now()
    with setup["engine"].begin() as connection:
        state = metadata.tables["MSP_VEHICLE_STATUS"]
        if protection in ("ON_RENT", "OVERDUE"):
            connection.execute(metadata.tables["MSP_RENTAL_CONTRACT"].insert().values(
                rental_contract_id="protected-rental", vehicle_id=ident, uid_token="isolated-customer",
                pickup_spot_master_id="root", actual_start_time=at, planned_end_date=at.date() + timedelta(days=1),
                contract_status=protection))
            connection.execute(state.update().where(state.c.vehicle_id == ident).values(status="ON_RENT"))
            expected = "VEHICLE_ALREADY_ON_RENT"
        else:
            expired = protection == "EXPIRED_RECEIPT_HOLD"
            connection.execute(metadata.tables["MSP_RESERVATION"].insert().values(
                reservation_id="protected-receipt", uid_token="isolated-customer", spot_master_id="root",
                model_id="test-model", assigned_vehicle_id=ident, vehicle_assignment_status="LOCKED",
                start_datetime=at - timedelta(hours=1), end_datetime=at + timedelta(days=1),
                reservation_status="EXPIRED" if expired else "HANDOVER_PENDING", handed_over_at=at,
                receipt_deadline_at=at + timedelta(hours=-1 if expired else 1)))
            connection.execute(state.update().where(state.c.vehicle_id == ident).values(
                status="DISABLED", status_reason=hold_reason("protected-receipt")))
            expected = "VEHICLE_RECEIPT_HOLD"
    before = {name: table_rows(setup, name) for name in (
        "MSP_VEHICLE_QR", "MSP_VEHICLE_QR_HISTORY", "MSP_VEHICLE_STATUS", "MSP_RENTAL_CONTRACT", "MSP_RESERVATION")}

    response = detach(client, headers, "QR-OLD") if operation == "delete" else link(client, headers, "QR-OLD")

    assert response.status_code == 409 and response.json()["errorCode"] == expected
    assert {name: table_rows(setup, name) for name in before} == before
