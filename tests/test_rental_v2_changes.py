from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import func, select

from app.jobs import expire_maintenance
from app.rental_common import local_date, midnight
from app.security import now
from test_handover_v2 import handover, external, pending_bookings, begin, form

BASE = "/api/v1/nadree/rental"


@pytest.mark.parametrize("minimum,maximum,found", [(0, 125, True), (125, 125, True), (126, 400, False), (125, None, True), (0, 124, False)])
def test_cc_range_uses_inclusive_model_cc(external, minimum, maximum, found):
    ctx = external
    today = local_date(SimpleNamespace(app=ctx["app"]), now())
    response = ctx["client"].post(BASE + "/availability", json={"startDate": str(today + timedelta(days=1)),
        "returnDate": str(today + timedelta(days=2)), "minCc": minimum, "maxCc": maximum, "deliveryRequested": False})
    assert response.status_code == 200, response.text
    assert bool(response.json()["items"]) is found


@pytest.mark.parametrize("fields", [{"cc": 125}, {"minCc": 126, "maxCc": 125},
                                   {"minCc": "125", "maxCc": None}, {"minCc": True, "maxCc": None}])
def test_invalid_or_retired_cc_input(external, fields):
    ctx = external
    today = local_date(SimpleNamespace(app=ctx["app"]), now())
    response = ctx["client"].post(BASE + "/availability", json={"startDate": str(today + timedelta(days=1)),
        "returnDate": str(today + timedelta(days=2)), "deliveryRequested": False, **fields})
    assert response.status_code == 422


def test_untracked_period_future_booking_and_early_release(external):
    ctx = external
    vehicles = ctx["tables"]["MSP_RENTAL_VEHICLE"]
    chosen = next(iter(ctx["qrs"]))
    with ctx["engine"].begin() as connection:
        connection.execute(vehicles.update().where(vehicles.c.vehicle_id != chosen).values(rental_enabled=0))
    req = SimpleNamespace(app=ctx["app"])
    today = local_date(req, now())
    with ctx["engine"].connect() as connection:
        number = connection.scalar(select(vehicles.c.plate_number_full).where(vehicles.c.vehicle_id == chosen))
    end = today + timedelta(days=2)
    key = str(uuid.uuid4())
    result = ctx["client"].post("/nadreego/vehicle/untracked-rent", headers=ctx["admin"],
        json={"vehicleNumber": number, "action": "START", "endDate": str(end), "qrCode": ctx["qrs"][chosen],
              "clientRequestId": key, "expectedStateVersion": 0})
    assert result.status_code == 200, result.text
    def available(start):
        response = ctx["client"].post(BASE + "/availability", json={"startDate": str(start),
            "returnDate": str(start + timedelta(days=1)), "minCc": 0, "maxCc": None, "deliveryRequested": False})
        assert response.status_code == 200, response.text
        return response.json()["items"]
    assert not available(end)
    assert available(end + timedelta(days=1))
    listing = ctx["client"].get(BASE + "/onsite/vehicles", headers=ctx["headers"],
        params={"shopId": "root", "returnDate": str(end)})
    assert listing.status_code == 200 and not listing.json()["items"]
    assert ctx["client"].post("/nadreego/vehicle/untracked-rent", headers=ctx["admin"],
        json={"vehicleNumber": number, "action": "END", "qrCode": ctx["qrs"][chosen],
              "untrackedRentId": key, "vehicleReturned": True}).status_code == 200
    assert available(end)
    assert ctx["client"].post("/nadreego/vehicle/untracked-rent", headers=ctx["admin"],
        json={"vehicleNumber": number, "action": "START", "endDate": str(end), "qrCode": ctx["qrs"][chosen],
              "clientRequestId": str(uuid.uuid4()), "expectedStateVersion": 2}).status_code == 200
    assert expire_maintenance(ctx["db"], ctx["settings"], at=midnight(req, end + timedelta(days=1))) == 0
    with ctx["engine"].connect() as connection:
        state = ctx["tables"]["MSP_VEHICLE_STATUS"]
        row = connection.execute(select(state).where(state.c.vehicle_id == chosen)).mappings().one()
        assert row["status"] == "UNTRACKED_RENT" and row["untracked_rent_until"] == end
        for name in ("MSP_RESERVATION", "MSP_RENTAL_CONTRACT", "MSP_RENTAL_HANDOVER"):
            assert connection.scalar(select(func.count()).select_from(ctx["db"].table(name))) == 0


def test_vehicle_id_onsite_selection_and_outcome_retry(external):
    ctx = external
    today = local_date(SimpleNamespace(app=ctx["app"]), now())
    vehicle = next(iter(ctx["qrs"]))
    body = {"vehicleId": vehicle, "returnDate": str(today + timedelta(days=2))}
    quote = ctx["client"].post(BASE + "/onsite/quote", headers=ctx["headers"], json=body)
    assert quote.status_code == 200, quote.text
    request = {**body, "quoteToken": quote.json()["quoteToken"], "clientRequestId": str(uuid.uuid4())}
    first = ctx["client"].post(BASE + "/onsite/requests", headers=ctx["headers"], json=request)
    assert first.status_code == 200, first.text
    again = ctx["client"].post(BASE + "/onsite/requests", headers=ctx["headers"], json=request)
    assert again.status_code == 200 and again.json()["item"]["reservationId"] == first.json()["item"]["reservationId"]
    assert first.json()["item"]["requestType"] == "WALK_IN"


def test_global_qr_verdict_without_foreign_vehicle_details(external, signin):
    ctx = external
    response = ctx["client"].post("/nadreego/vehicle/qr/availability", headers=signin("outsider"),
        json={"qrCode": next(iter(ctx["qrs"].values()))})
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "success", "canRegister": False, "assignment": "OTHER_SHOP", "reasonCode": "QR_ALREADY_ISSUED"}
    response = ctx["client"].post("/nadreego/vehicle/qr/validate", headers=signin("outsider"),
        json={"qrCode": next(iter(ctx["qrs"].values()))})
    assert response.status_code == 409 and response.json()["errorCode"] == "QR_ALREADY_ISSUED"


def test_replacement_preserves_price_and_restarts_only_handover(handover):
    ctx = handover
    begin(ctx)
    assert form(ctx, passportNumber="TEST-OLD-FORM").status_code == 200
    path = "/nadreego/booking/BO" + ctx["rid"]
    options = ctx["client"].get(path + "/replacement-vehicles", headers=ctx["admin"])
    assert options.status_code == 200, options.text
    data = options.json()
    target = data["items"][0]["vehicleId"]
    body = {"vehicleId": target, "expectedVehicleId": data["assignedVehicleId"],
            "expectedUpdatedAt": data["reservationUpdatedAt"], "reason": "Test replacement"}
    changed = ctx["client"].patch(path + "/vehicle", headers=ctx["admin"], json=body)
    assert changed.status_code == 200, changed.text
    item = changed.json()
    assert item["finalPrice"] == 25 and item["handoverRestartRequired"] is True
    assert item["handoverId"] != ctx["hid"]
    h = ctx["db"].table("MSP_RENTAL_HANDOVER")
    with ctx["engine"].connect() as connection:
        old = connection.execute(select(h).where(h.c.handover_id == ctx["hid"])).mappings().one()
        assert old["handover_status"] == "CANCELED" and old["cancel_reason"] == "VEHICLE_CHANGED"
        assert connection.scalar(select(func.count()).select_from(h)) == 2
    assert ctx["client"].patch(path + "/vehicle", headers=ctx["admin"], json=body).json()["errorCode"] == "RESERVATION_VEHICLE_CONFLICT"
