from datetime import timedelta
import hashlib
import hmac

from pydantic import SecretStr
import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, select

from app.rental_schema import metadata
from app.security import now


@pytest.fixture
def equipment(setup):
    metadata.create_all(setup["engine"])
    extra = MetaData()
    Table("MSP_SENSOR", extra, Column("sensor_id", String(36), primary_key=True), Column("sensor_code", String(50)),
          Column("vehicle_id", String(36)), Column("is_active", Integer))
    Table("MSP_SENSOR_SPOT_HISTORY", extra, Column("history_id", Integer, primary_key=True),
          Column("sensor_id", String(36)), Column("spot_master_id", String(36)), Column("released_at", DateTime))
    Table("MSP_VEHICLE", extra, Column("vehicle_id", String(36), primary_key=True), Column("vehicle_code", String(50)),
          Column("plate_number", String(25)), Column("vehicle_type", String(30)), Column("model_name", String(50)),
          Column("is_active", Integer), Column("created_by", String(36)), Column("created_at", DateTime), Column("updated_at", DateTime))
    Table("MSP_VEHICLE_SPOT_HISTORY", extra, Column("history_id", Integer, primary_key=True), Column("vehicle_id", String(36)),
          Column("spot_master_id", String(36)), Column("assigned_at", DateTime), Column("assigned_by", String(36)),
          Column("released_at", DateTime), Column("reason", String(200)))
    extra.create_all(setup["engine"])
    with setup["engine"].begin() as conn:
        conn.execute(extra.tables["MSP_SENSOR"].insert().values(sensor_id="test-sensor-id", sensor_code="sensor-code-not-qr", is_active=1))
        conn.execute(extra.tables["MSP_SENSOR_SPOT_HISTORY"].insert().values(sensor_id="test-sensor-id", spot_master_id="root"))
        conn.execute(metadata.tables["MSP_VEHICLE_MODEL"].insert().values(model_id="test-model", brand="Test",
                                                                      model_name="Test model", vehicle_type="SCOOTER"))
    setup["settings"].qr_hash_key = SecretStr("isolated-vehicle-qr-test-key-not-for-production")
    return extra.tables


def register(client, headers, sensor=False, qr="testQr123123", plate="NEW-TEST"):
    return client.post("/nadreego/vehicle/create", headers=headers, json={"sensorId": "test-sensor-id" if sensor else None,
        "qrToken": qr, "brand": "Test", "vehicleName": "Test model", "modelId": "test-model", "plateNumber": plate})


def lookup(client, headers, qr="testQr123123"):
    return client.post("/nadreego/vehicle/qr/validate", headers=headers, json={"qrCode": qr})


@pytest.mark.parametrize("sensor", [False, True])
def test_qr_identifies_vehicle_with_optional_sensor(client, signin, setup, equipment, sensor):
    headers = signin()
    created = register(client, headers, sensor)
    assert created.status_code == 200, created.text
    response = lookup(client, headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["vehicleId"] == created.json()["vehicleId"]
    assert data["vehicle"]["vehicleNo"] == "NEW-TEST"
    assert data["equipmentType"] == ("QR_WITH_SENSOR" if sensor else "QR_ONLY")
    assert data["sensorId"] == ("test-sensor-id" if sensor else None)
    assert ("LOCATION" in data["availableActions"]) == sensor
    assert "qr_code_hash" not in response.text and "sensor-code-not-qr" not in response.text
    with setup["engine"].connect() as conn:
        stored = conn.scalar(select(metadata.tables["MSP_VEHICLE_QR"].c.qr_code_hash))
    expected = hmac.new(setup["settings"].qr_hash_key.get_secret_value().encode(), b"testQr123123", hashlib.sha256).hexdigest()
    assert stored == expected and stored != "testQr123123"
    changed = client.post("/nadreego/vehicle/priceChange", headers=headers,
        json={"vehicleNumber": data["vehicle"]["vehicleNo"], "priceType": "PREMIUM", "priceInfo": 45})
    assert changed.status_code == 200, changed.text
    assert lookup(client, headers).json()["data"]["vehicleId"] == data["vehicleId"]


@pytest.mark.parametrize("qr", ["sensor-code-not-qr", "test-sensor-id", "testqr123123", "unknown"])
def test_sensor_code_is_not_vehicle_qr(client, signin, equipment, qr):
    headers = signin()
    assert register(client, headers, True).status_code == 200
    assert lookup(client, headers, qr).status_code == 404


def test_qr_scope_and_auth(client, signin, equipment):
    assert register(client, signin()).status_code == 200
    assert lookup(client, {}).status_code == 401
    assert lookup(client, signin("outsider")).status_code == 404
    assert lookup(client, signin("general")).status_code == 200


@pytest.mark.parametrize("status,expected", [("INACTIVE", 409), ("EXPIRED", 410)])
def test_inactive_or_expired_qr_is_rejected(client, signin, setup, equipment, status, expected):
    headers = signin()
    assert register(client, headers).status_code == 200
    with setup["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_VEHICLE_QR"].update().values(qr_status=status))
    assert lookup(client, headers).status_code == expected


def test_duplicate_vehicle_qr_rejected_without_new_vehicle(client, signin, equipment):
    headers = signin()
    assert register(client, headers).status_code == 200
    response = register(client, headers, plate="ANOTHER")
    assert response.status_code == 409 and response.json()["errorCode"] == "QR_ALREADY_ISSUED"


def test_detaching_sensor_keeps_vehicle_qr(client, signin, equipment):
    headers = signin()
    created = register(client, headers, True).json()
    response = client.post("/nadreego/sensor/delete", headers=headers, json={"vehicleNumber": "NEW-TEST", "division": "SENSOR"})
    assert response.status_code == 200, response.text
    data = lookup(client, headers).json()["data"]
    assert data["vehicleId"] == created["vehicleId"] and data["equipmentType"] == "QR_ONLY"
    assert data["sensorId"] is None and data["qrStatus"] == "ACTIVE"


@pytest.mark.parametrize("state,expected", [("LINKED", 409), ("FOREIGN", 404), ("RENTED", 409)])
def test_optional_sensor_linking_is_still_validated(client, signin, setup, equipment, state, expected):
    with setup["engine"].begin() as conn:
        if state == "LINKED":
            conn.execute(equipment["MSP_SENSOR"].update().values(vehicle_id="another-vehicle"))
        elif state == "FOREIGN":
            conn.execute(equipment["MSP_SENSOR_SPOT_HISTORY"].update().values(spot_master_id="foreign"))
        else:
            conn.execute(metadata.tables["MSP_RENTAL_CONTRACT"].insert().values(rental_contract_id="ongoing",
                vehicle_id="another-vehicle", sensor_id="test-sensor-id", uid_token="customer", pickup_spot_master_id="root",
                planned_end_date=now().date() + timedelta(days=1), contract_status="ON_RENT"))
    assert register(client, signin(), True).status_code == expected
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(equipment["MSP_VEHICLE"].c.vehicle_id)) is None
