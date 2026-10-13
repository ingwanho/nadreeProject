from datetime import timedelta

import pytest
from sqlalchemy import select

from app.security import now
from test_nadri_flow import prepare_rental_schema


@pytest.fixture
def transfer(setup):
    tables = prepare_rental_schema(setup)
    with setup["engine"].begin() as conn:
        conn.execute(tables["MSP_VEHICLE_MODEL"].insert().values(model_id="move-model", brand="Test", model_name="Test",
                                                               vehicle_type="SCOOTER"))
        conn.execute(tables["MSP_VEHICLE"].insert().values(vehicle_id="move-vehicle", plate_number="MOVE-TEST", is_active=1))
        conn.execute(tables["MSP_RENTAL_VEHICLE"].insert().values(vehicle_id="move-vehicle", model_id="move-model"))
        conn.execute(tables["MSP_VEHICLE_SPOT_HISTORY"].insert().values(vehicle_id="move-vehicle", spot_master_id="root"))
        conn.execute(tables["MSP_VEHICLE_STATUS"].insert().values(vehicle_id="move-vehicle", status="AVAILABLE", status_changed_at=now()))
    return tables


@pytest.mark.parametrize("blocked", [None, "RESERVATION", "CONTRACT", "FOREIGN"])
def test_transfer_preserves_assignment_and_limits_scope(setup, signin, transfer, blocked):
    with setup["engine"].begin() as conn:
        if blocked == "RESERVATION":
            conn.execute(transfer["MSP_RESERVATION"].insert().values(reservation_id="move-reservation", uid_token="test",
                spot_master_id="root", model_id="move-model", assigned_vehicle_id="move-vehicle", reservation_status="APPROVED",
                start_datetime=now() + timedelta(days=1), end_datetime=now() + timedelta(days=2)))
        if blocked == "CONTRACT":
            conn.execute(transfer["MSP_RENTAL_CONTRACT"].insert().values(rental_contract_id="move-contract", uid_token="test",
                vehicle_id="move-vehicle", pickup_spot_master_id="root", planned_end_date=now().date() + timedelta(days=2),
                contract_status="ON_RENT", actual_start_time=now()))
    response = setup["client"].post("/nadreego/vehicle/spotChange", headers=signin(),
        json={"vehicleNumber": "MOVE-TEST", "spotCode": "foreign" if blocked == "FOREIGN" else "child"})
    assert response.status_code == (404 if blocked == "FOREIGN" else 409 if blocked else 200), response.text
    history = transfer["MSP_VEHICLE_SPOT_HISTORY"]
    with setup["engine"].connect() as conn:
        rows = list(conn.execute(select(history).order_by(history.c.history_id)).mappings())
    assert rows[-1]["spot_master_id"] == ("root" if blocked else "child")
    assert len(rows) == (1 if blocked else 2)
    if not blocked:
        assert rows[0]["released_at"] and rows[1]["released_at"] is None
