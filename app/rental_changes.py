"""Replace an approved reservation's vehicle without changing the agreed price."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import update

from app.availability import apply_assignments, compute_assignment, price_key, reservation_history, reservation_price
from app.db import transaction
from app.errors import Problem
from app.handover import current, is_v2, notify, prepare, save
from app.handover_inputs import ReplaceVehicle
from app.headers import bearer
from app.pricing import load_tiers
from app.rental_common import context, contracts_for, fleet, iso, lock_key
from app.rentals import booking, require_no_contract
from app.security import now
from app.vehicles import vehicle_view

router = APIRouter(tags=["W06 Reservations and rentals"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


def _candidate(request, session, root, reservation, vehicles, contracts, ident):
    item = vehicles.get(ident)
    if not item or ident == reservation["assigned_vehicle_id"]:
        raise Problem(409, "VEHICLE_UNAVAILABLE")
    tiers = load_tiers(request, session, root["spot_master_id"])
    if price_key(item, tiers) != reservation_price(reservation, vehicles, tiers):
        raise Problem(409, "VEHICLE_UNAVAILABLE")
    qr = item.get("qr")
    if not qr or qr["qr_status"] != "ACTIVE" or qr.get("expired_at") and qr["expired_at"] <= now():
        raise Problem(409, "VEHICLE_UNAVAILABLE")
    criteria = dict(reservation.get("required_criteria_json") or {})
    if criteria.get("requestType") in ("ONSITE", "WALK_IN"):
        criteria["onsiteVehicleId"] = ident
    candidate = dict(reservation, assigned_vehicle_id=ident, vehicle_assignment_status="LOCKED", required_criteria_json=criteria)
    assignments, records = compute_assignment(request, session, root, vehicles, contracts, candidate=candidate,
                                               omit_reservation=reservation["reservation_id"])
    return candidate, assignments, records


def _ready(request, session, root, booked_no):
    if not booked_no.startswith("BO") or not 2 < len(booked_no) <= 52 or any(c.isspace() for c in booked_no):
        raise Problem(422, "INVALID_INPUT")
    reservation = booking(request, session, root, booked_no)
    if reservation["reservation_status"] != "APPROVED":
        raise Problem(409, "RESERVATION_STATE_INVALID")
    require_no_contract(request, session, reservation)
    return reservation


@router.get("/nadreego/booking/{booked_no}/replacement-vehicles")
def replacement_vehicles(booked_no: str, request: Request, page: int = Query(1, ge=1),
                         pageSize: int = Query(20, ge=1, le=100), session=DB):
    _, root = context(request, session)
    r = _ready(request, session, root, booked_no)
    vehicles = fleet(request, session, root, model_id=r["model_id"])
    contracts = contracts_for(request, session, list(vehicles))
    items = []
    for ident, item in sorted(vehicles.items()):
        try:
            _candidate(request, session, root, r, vehicles, contracts, ident)
        except Problem as error:
            if error.code in ("VEHICLE_UNAVAILABLE", "PRICE_NOT_CONFIGURED"):
                continue
            raise
        items.append(vehicle_view(request, item, contracts))
    return {"status": "success", "items": items[(page - 1) * pageSize:page * pageSize], "page": page,
            "pageSize": pageSize, "totalCount": len(items), "hasNext": page * pageSize < len(items),
            "assignedVehicleId": r["assigned_vehicle_id"], "reservationUpdatedAt": iso(request, r["updated_at"])}


@router.patch("/nadreego/booking/{booked_no}/vehicle")
def replace_vehicle(booked_no: str, body: ReplaceVehicle, request: Request, session=DB):
    actor, root = context(request, session, write=True)
    r = _ready(request, session, root, booked_no)
    try:
        expected = datetime.fromisoformat(body.expectedUpdatedAt)
        if expected.tzinfo is None:
            raise ValueError
        expected = expected.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise Problem(422, "INVALID_INPUT") from None
    if r["assigned_vehicle_id"] != body.expectedVehicleId or r["updated_at"] != expected:
        raise Problem(409, "RESERVATION_VEHICLE_CONFLICT")
    lock_key(session, "nadri-model", root["spot_master_id"] + ":" + r["model_id"])
    vehicles = fleet(request, session, root, model_id=r["model_id"], lock=True)
    contracts = contracts_for(request, session, list(vehicles))
    candidate, assignments, records = _candidate(request, session, root, r, vehicles, contracts, body.vehicleId)
    apply_assignments(request, session, assignments, records, actor.admin["admin_id"], skip=r["reservation_id"])
    values = {"assigned_vehicle_id": body.vehicleId, "vehicle_assignment_status": "PROVISIONAL",
              "vehicle_assigned_at": now(), "updated_at": now(), "required_criteria_json": candidate["required_criteria_json"]}
    h = current(request, session, r["reservation_id"], include_canceled=False) if is_v2(r) else None
    if h:
        save(request, session, h, handover_status="CANCELED", canceled_at=now(), cancel_reason="VEHICLE_CHANGED")
    table = request.app.state.db.table("MSP_RESERVATION")
    session.execute(update(table).where(table.c.reservation_id == r["reservation_id"]).values(**values))
    reservation_history(request, session, r, values, "VEHICLE_REASSIGNED", actor.admin["admin_id"], body.reason)
    new_h = prepare(request, session, {**r, **values}, h["final_price"]) if h else None
    if new_h:
        notify(request, session, new_h, "HANDOVER_VEHICLE_CHANGED", customer=True)
    return {"status": "success", "bookedNo": booked_no, "reservationId": r["reservation_id"],
            "vehicleId": body.vehicleId, "handoverId": new_h["handover_id"] if new_h else None,
            "handoverRestartRequired": new_h is not None, "finalPrice": new_h["final_price"] if new_h else None,
            "reservationUpdatedAt": iso(request, values["updated_at"])}
