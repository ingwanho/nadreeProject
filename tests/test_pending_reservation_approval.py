from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.availability import apply_assignments
from app.errors import Problem
from app.security import now, sign_user_access
from test_nadri_flow import prepare_rental_schema


@pytest.fixture
def pending_bookings(setup):
    tables = prepare_rental_schema(setup)
    with setup["engine"].begin() as conn:
        conn.execute(tables["MSP_VEHICLE_MODEL"].insert().values(
            model_id="pending-model", brand="Test", model_name="Test", cc=125,
            vehicle_type="SCOOTER", is_active=1))
        conn.execute(tables["MSP_RENTAL_TIER"].insert().values(
            spot_master_id=None, price=10, min_cc=0, max_cc=1000, tier_type="BASE"))
        for i in range(3):
            ident = "pending-vehicle-" + str(i)
            conn.execute(tables["MSP_RENTAL_VEHICLE"].insert().values(
                vehicle_id=ident, model_id="pending-model", plate_number_full="PENDING-" + str(i),
                price_type="BASIC", rental_enabled=1))
            conn.execute(tables["MSP_VEHICLE"].insert().values(vehicle_id=ident, is_active=1))
            conn.execute(tables["MSP_VEHICLE_SPOT_HISTORY"].insert().values(vehicle_id=ident, spot_master_id="root"))
            conn.execute(tables["MSP_VEHICLE_STATUS"].insert().values(
                vehicle_id=ident, status="AVAILABLE", status_changed_at=now()))
        for i in range(5):
            conn.execute(tables["MSP_RENTAL_USER"].insert().values(uid_token="pending-user-" + str(i)))
    # Only PayPal verification is mocked; inventory, solver, transactions and
    # approval writes use the real API implementation and isolated database.
    setup["app"].state.paypal.verify_merchant = lambda merchant: None
    def request_booking(index, offset=0, expected=200):
        start = date.today() + timedelta(days=7 + offset)
        response = setup["client"].post("/api/v1/nadree/rental/request", headers={
            "Authorization": "Bearer " + sign_user_access(setup["settings"], "pending-user-" + str(index))},
            json={"spotMasterId": "root", "modelId": "pending-model", "startDate": str(start),
                  "returnDate": str(start + timedelta(days=3)), "totalPrice": 30,
                  "currency": "USD", "deliveryRequested": False})
        assert response.status_code == expected, response.text
        return response.json()
    return tables, request_booking


@pytest.mark.parametrize("offsets", [(0, 0, 0), (0, 4, 8, 22)])
@pytest.mark.parametrize("approval_index", [0, 1, 2])
def test_approval_keeps_other_pending_holds(setup, signin, pending_bookings, offsets, approval_index):
    tables, request_booking = pending_bookings
    ids = [request_booking(i, offset)["reservationId"] for i, offset in enumerate(offsets)]
    target = ids[approval_index]
    r = tables["MSP_RESERVATION"]
    with setup["engine"].connect() as conn:
        before = {row["reservation_id"]: dict(row) for row in conn.execute(select(r)).mappings()}
    response = setup["client"].post("/nadreego/booking/action", headers=signin(),
        json={"bookedNo": "BO" + target, "action": "APPROVE"})
    assert response.status_code == 200, response.text
    with setup["engine"].connect() as conn:
        rows = {row["reservation_id"]: dict(row) for row in conn.execute(select(r)).mappings()}
        assert rows[target]["reservation_status"] == "APPROVED"
        assert rows[target]["vehicle_assignment_status"] == "PROVISIONAL"
        assert rows[target]["assigned_vehicle_id"] is not None
        for ident in set(ids) - {target}:
            assert rows[ident] == before[ident]
            h = tables["MSP_RESERVATION_HISTORY"]
            assert conn.scalar(select(func.count()).select_from(h).where(
                h.c.reservation_id == ident, h.c.event_type == "VEHICLE_REASSIGNED")) == 0
    if len(set(offsets)) == 1:
        blocked = request_booking(3, expected=409)
        assert blocked["errorCode"] == "RENTAL_UNAVAILABLE"


def test_approved_booking_can_still_be_reassigned(setup, signin, pending_bookings, monkeypatch):
    from app import availability
    tables, request_booking = pending_bookings
    ids = [request_booking(i)["reservationId"] for i in range(3)]
    headers = signin()
    approve = lambda ident: setup["client"].post("/nadreego/booking/action", headers=headers,
        json={"bookedNo": "BO" + ident, "action": "APPROVE"})
    assert approve(ids[0]).status_code == 200
    r = tables["MSP_RESERVATION"]
    with setup["engine"].connect() as conn:
        original = conn.scalar(select(r.c.assigned_vehicle_id).where(r.c.reservation_id == ids[0]))
    solve = availability.solve_intervals
    def move_approved(jobs, fixed, **kwargs):
        result = solve(jobs, fixed, **kwargs)
        if result[ids[0]] == original:
            other = next(ident for ident in ids[1:] if result[ident] != original)
            result[ids[0]], result[other] = result[other], result[ids[0]]
        return result
    monkeypatch.setattr(availability, "solve_intervals", move_approved)
    assert approve(ids[1]).status_code == 200
    with setup["engine"].connect() as conn:
        rows = {row["reservation_id"]: row for row in conn.execute(select(r)).mappings()}
        assert rows[ids[0]]["assigned_vehicle_id"] != original
        assert rows[ids[0]]["vehicle_assignment_status"] == "REALLOCATED"
        assert rows[ids[2]]["reservation_status"] == "REQUESTED"
        assert rows[ids[2]]["assigned_vehicle_id"] is None
        assert rows[ids[0]]["assigned_vehicle_id"] != rows[ids[1]]["assigned_vehicle_id"]
        h = tables["MSP_RESERVATION_HISTORY"]
        assert conn.scalar(select(func.count()).select_from(h).where(
            h.c.reservation_id == ids[0], h.c.event_type == "VEHICLE_REASSIGNED")) == 1


def test_changed_approved_booking_still_raises_conflict(setup, pending_bookings):
    tables, request_booking = pending_bookings
    ident = request_booking(0)["reservationId"]
    r = tables["MSP_RESERVATION"]
    with Session(setup["engine"]) as session, session.begin():
        snapshot = dict(session.execute(select(r).where(r.c.reservation_id == ident)).mappings().one())
        snapshot.update(reservation_status="APPROVED", vehicle_assignment_status="PROVISIONAL",
                        assigned_vehicle_id="pending-vehicle-0")
        session.execute(r.update().where(r.c.reservation_id == ident).values(reservation_status="CANCELED"))
        with pytest.raises(Problem) as error:
            apply_assignments(SimpleNamespace(app=setup["app"]), session,
                {ident: "pending-vehicle-1"}, {ident: snapshot}, "primary")
        assert error.value.code == "RESERVATION_CHANGED"
