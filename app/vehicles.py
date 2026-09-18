import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.availability import apply_assignments, compute_assignment
from app.db import require_columns, transaction
from app.errors import Problem
from app.headers import bearer
from app.pricing import daily_price, load_tiers, tier_view
from app.rental_common import (action_result, by_number, context, contracts_for, day_end, effective_state,
    expire_maintenance, fleet, is_open, local_date, lock_key, page_result, qr_digest, resolve_spot, rows, verify_qr)
from app.rental_inputs import Detach, Move, Page, Qr, Repair, VehicleCreate, VehicleNumber
from app.responses import Status
from app.security import now

router = APIRouter(tags=["W03 Vehicles and QR"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


def qr_history(request, session, qr, actor, event, reason=None):
    t = request.app.state.db.table("MSP_VEHICLE_QR_HISTORY")
    session.execute(t.insert().values(qr_id=qr["qr_id"], vehicle_id=qr["vehicle_id"],
        qr_code_hash=qr["qr_code_hash"], qr_status=qr["qr_status"], change_type=event,
        valid_from=now(), change_reason=reason, changed_by=actor, created_at=now()))


def available_actions(request, item, contracts):
    ident = item["vehicle"]["vehicle_id"]
    if any(c["vehicle_id"] == ident and is_open(c) for c in contracts):
        return ["PRICE_CHANGE"] + (["LOCATION"] if len(item["sensors"]) == 1 else [])
    result = ["PRICE_CHANGE", "SPOT_CHANGE"]
    if effective_state(request, item, contracts) in ("AVAILABLE", "MAINTENANCE"):
        result.append("REPAIR")
    if item["qr"] and item["qr"]["qr_status"] == "ACTIVE":
        result.append("QR_DELETE")
    if len(item["sensors"]) == 1:
        result.extend(["SENSOR_DELETE", "LOCATION"])
    return result


def vehicle_view(request, item, contracts):
    v, rv, model = item["vehicle"], item["rental"], item["model"] or {}
    return dict(vehicleId=v["vehicle_id"], vehicleNo=rv["plate_number_full"] or v["plate_number"],
        plateNumberFull=rv["plate_number_full"], modelId=rv["model_id"], brand=model.get("brand"),
        modelName=model.get("model_name"), cc=model.get("cc"), vehicleType=model.get("vehicle_type"),
        vehicleImageKey=rv["vehicle_image_key"], vehicleStatus=effective_state(request, item, contracts))


@router.post("/nadreego/vehicle/create")
def create_vehicle(body: VehicleCreate, request: Request, session: Session = DB):
    actor, root = context(request, session, write=True)
    db = request.app.state.db
    v, rv, models = (db.table(n) for n in ("MSP_VEHICLE", "MSP_RENTAL_VEHICLE", "MSP_VEHICLE_MODEL"))
    model = session.execute(select(models).where(models.c.model_id == body.modelId, models.c.is_active == 1)).mappings().first()
    if not model:
        raise Problem(404, "VEHICLE_MODEL_NOT_FOUND")
    if body.brand != model["brand"] or body.vehicleName != model["model_name"]:
        raise Problem(409, "VEHICLE_MODEL_MISMATCH")
    plate = body.plateNumber.strip()
    lock_key(session, "plate", plate.casefold())
    if session.execute(select(v.c.vehicle_id).outerjoin(rv, rv.c.vehicle_id == v.c.vehicle_id)
        .where(or_(v.c.plate_number == plate, rv.c.plate_number_full == plate))).first():
        raise Problem(409, "VEHICLE_NUMBER_EXISTS")
    sensor = None
    st, sh = db.table("MSP_SENSOR"), db.table("MSP_SENSOR_SPOT_HISTORY")
    if body.sensorId:
        sensor = session.execute(select(st).where(st.c.sensor_id == body.sensorId, st.c.is_active == 1).with_for_update()).mappings().first()
        memberships = rows(session, sh, sh.c.sensor_id == body.sensorId, sh.c.released_at.is_(None))
        if not sensor or len(memberships) != 1 or memberships[0]["spot_master_id"] != root["spot_master_id"]:
            raise Problem(404, "SENSOR_NOT_FOUND")
        if sensor["vehicle_id"] is not None:
            raise Problem(409, "SENSOR_ALREADY_LINKED")
    digest = None
    if body.qrToken:
        digest = qr_digest(request, body.qrToken.get_secret_value())
        lock_key(session, "qr", digest)
        for name in ("MSP_VEHICLE_QR", "MSP_VEHICLE_QR_HISTORY"):
            t = db.table(name)
            if session.execute(select(t.c.vehicle_id).where(t.c.qr_code_hash == digest)).first():
                raise Problem(409, "QR_ALREADY_ISSUED")
    ident, at = str(uuid.uuid4()), now()
    values = dict(vehicle_id=ident, vehicle_code="NR-" + ident, plate_number=plate if len(plate) <= 20 else None,
        vehicle_type=model["vehicle_type"], model_name=model["model_name"], is_active=1,
        created_by=actor.admin["admin_id"], created_at=at, updated_at=at)
    require_columns(v, values)
    session.execute(v.insert().values(**values))
    session.execute(rv.insert().values(vehicle_id=ident, model_id=body.modelId, plate_number_full=plate,
        vehicle_image_key=body.vehicleImageKey, price_type="BASIC", premium_daily_price=None,
        rental_enabled=1, created_at=at, updated_at=at))
    state, h = db.table("MSP_VEHICLE_STATUS"), db.table("MSP_VEHICLE_SPOT_HISTORY")
    session.execute(state.insert().values(vehicle_id=ident, status="AVAILABLE", status_changed_at=at,
        changed_by=actor.admin["admin_id"], created_at=at, updated_at=at))
    session.execute(h.insert().values(vehicle_id=ident, spot_master_id=root["spot_master_id"],
        assigned_at=at, assigned_by=actor.admin["admin_id"], reason="Rental registration"))
    if sensor:
        session.execute(update(st).where(st.c.sensor_id == body.sensorId).values(vehicle_id=ident))
    if digest:
        qr = dict(vehicle_id=ident, qr_id=str(uuid.uuid4()), qr_code_hash=digest, qr_status="ACTIVE", issued_at=at, created_at=at, updated_at=at)
        session.execute(db.table("MSP_VEHICLE_QR").insert().values(**qr))
        qr_history(request, session, qr, actor.admin["admin_id"], "ISSUED")
    return dict(status="success", vehicleId=ident, iot={"sensorId": body.sensorId, "sensorStatus": "LINKED"} if sensor else {},
                brand=model["brand"], vehicleName=model["model_name"])


@router.post("/nadreego/vehicle/qr/validate")
def validate_qr(body: Qr, request: Request, session: Session = DB):
    actor, root = context(request, session)
    limiter = request.app.state.limiter
    limiter.check("qr-admin:" + actor.admin["admin_id"], limit=60, seconds=60)
    limiter.check("qr-ip:" + (request.client.host if request.client else "unknown"), limit=120, seconds=60)
    qr = verify_qr(request, session, root, body.qrCode.get_secret_value())
    return dict(status=True, errorCode=None, data=dict(vehicleId=qr["vehicle_id"], qrId=qr["qr_id"], qrStatus="ACTIVE"))


@router.post("/nadreego/sensor/delete", response_model=Status)
def detach(body: Detach, request: Request, session: Session = DB):
    actor, root = context(request, session, write=True)
    item = by_number(fleet(request, session, root, lock=True), body.vehicleNumber)
    ident = item["vehicle"]["vehicle_id"]
    if any(is_open(c) for c in contracts_for(request, session, [ident])):
        raise Problem(409, "VEHICLE_ALREADY_ON_RENT")
    db = request.app.state.db
    if body.division == "SENSOR":
        if len(item["sensors"]) != 1:
            raise Problem(404 if not item["sensors"] else 409, "SENSOR_NOT_LINKED")
        t = db.table("MSP_SENSOR")
        session.execute(update(t).where(t.c.sensor_id == item["sensors"][0]["sensor_id"]).values(vehicle_id=None))
    else:
        if item["qr"] is None:
            raise Problem(404, "QR_NOT_FOUND")
        if item["qr"]["qr_status"] != "INACTIVE":
            t = db.table("MSP_VEHICLE_QR")
            session.execute(update(t).where(t.c.vehicle_id == ident).values(qr_status="INACTIVE", updated_at=now()))
            qr_history(request, session, {**item["qr"], "qr_status": "INACTIVE"}, actor.admin["admin_id"], "INACTIVATED")
    return {"status": "success"}


@router.post("/nadreego/vehicle/location")
def location(body: VehicleNumber, request: Request, session: Session = DB):
    _, root = context(request, session)
    item = by_number(fleet(request, session, root), body.vehicleNumber)
    if len(item["sensors"]) != 1:
        raise Problem(404 if not item["sensors"] else 409, "SENSOR_NOT_LINKED")
    sensor = item["sensors"][0]
    if not sensor.get("sensor_code"):
        raise Problem(409, "SENSOR_CODE_INVALID")
    return {"status": "success", "geopoint": request.app.state.locations.get(sensor["sensor_code"])}


@router.post("/nadreego/vehicle/repair")
def repair(body: Repair, request: Request, session: Session = DB):
    actor, root = context(request, session, write=True)
    vehicles = fleet(request, session, root, lock=True)
    item = by_number(vehicles, body.vehicleNumber)
    ident = item["vehicle"]["vehicle_id"]
    vehicles = {k: v for k, v in vehicles.items() if v["rental"]["model_id"] == item["rental"]["model_id"]}
    contracts = contracts_for(request, session, list(vehicles))
    if any(c["vehicle_id"] == ident and is_open(c) for c in contracts):
        raise Problem(409, "VEHICLE_ALREADY_ON_RENT")
    expire_maintenance(request, session, vehicles, contracts)
    if effective_state(request, item, contracts) not in ("AVAILABLE", "MAINTENANCE"):
        raise Problem(409, "VEHICLE_UNAVAILABLE")
    if body.date < local_date(request, now()):
        raise Problem(400, "MAINTENANCE_DATE_INVALID")
    begin = item["state"]["status_changed_at"] if item["state"]["status"] == "MAINTENANCE" else now()
    assignments, reservations = compute_assignment(request, session, root, vehicles, contracts, maintenance=(ident, begin, day_end(request, body.date)))
    apply_assignments(request, session, assignments, reservations, actor.admin["admin_id"])
    t = request.app.state.db.table("MSP_VEHICLE_STATUS")
    session.execute(update(t).where(t.c.vehicle_id == ident).values(status="MAINTENANCE", maintenance_until=body.date,
        status_changed_at=begin, status_reason=body.reason, changed_by=actor.admin["admin_id"], updated_at=now()))
    return action_result(request, actor, "MAINTENANCE", dict(vehicleId=ident, vehicleStatus="MAINTENANCE", maintenanceUntil=body.date))


@router.post("/nadreego/vehicle/spotChange")
def move(body: Move, request: Request, session: Session = DB):
    actor, root = context(request, session, write=True)
    target = resolve_spot(request, session, root, body.spotCode, lock=True)
    item = by_number(fleet(request, session, root, lock=True), body.vehicleNumber)
    ident = item["vehicle"]["vehicle_id"]
    if target["spot_master_id"] == root["spot_master_id"]:
        return dict(status="success", spotMasterId=root["spot_master_id"])
    if any(is_open(c) for c in contracts_for(request, session, [ident])):
        raise Problem(409, "VEHICLE_ALREADY_ON_RENT")
    db = request.app.state.db
    reservations = db.table("MSP_RESERVATION")
    if session.execute(select(reservations.c.reservation_id).where(reservations.c.assigned_vehicle_id == ident,
        reservations.c.reservation_status.in_(["REQUESTED", "APPROVED", "HANDED_OVER"]))).first():
        raise Problem(409, "VEHICLE_HAS_RESERVATIONS")
    at = now()
    h = db.table("MSP_VEHICLE_SPOT_HISTORY")
    session.execute(update(h).where(h.c.vehicle_id == ident, h.c.released_at.is_(None)).values(released_at=at))
    session.execute(h.insert().values(vehicle_id=ident, spot_master_id=target["spot_master_id"],
        assigned_at=at, assigned_by=actor.admin["admin_id"], reason="Rental spot transfer"))
    if len(item["sensors"]) > 1:
        raise Problem(409, "SENSOR_STATE_INCONSISTENT")
    for sensor in item["sensors"]:
        sh, st = db.table("MSP_SENSOR_SPOT_HISTORY"), db.table("MSP_SENSOR")
        existing = rows(session, sh, sh.c.sensor_id == sensor["sensor_id"], sh.c.released_at.is_(None))
        if len(existing) != 1 or existing[0]["spot_master_id"] != root["spot_master_id"]:
            raise Problem(409, "SENSOR_SPOT_INCONSISTENT")
        session.execute(update(sh).where(sh.c.history_id == existing[0]["history_id"]).values(released_at=at))
        session.execute(sh.insert().values(sensor_id=sensor["sensor_id"], spot_master_id=target["spot_master_id"],
            assigned_at=at, assigned_by=actor.admin["admin_id"], reason="Rental spot transfer"))
        session.execute(update(st).where(st.c.sensor_id == sensor["sensor_id"]).values(spot_id=target["org_id"]))
    if item["qr"]:
        qr_history(request, session, item["qr"], actor.admin["admin_id"], "TRANSFERRED", "Rental spot transfer")
    return dict(status="success", spotMasterId=target["spot_master_id"])


@router.post("/nadreego/brand")
def brands(body: Page, request: Request, session: Session = DB):
    _, root = context(request, session)
    items = fleet(request, session, root)
    tiers = load_tiers(request, session, root["spot_master_id"])
    models = {}
    for item in items.values():
        model = item["model"]
        if model is None:
            continue
        key = model["model_id"]
        if key not in models:
            basic = {**item, "rental": {**item["rental"], "price_type": "BASIC", "premium_daily_price": None}}
            models[key] = dict(modelId=key, brand=model["brand"], modelName=model["model_name"], cc=model["cc"],
                modelImageKey=model["model_image_key"], vehicleCount=0, price=daily_price(basic, tiers))
        models[key]["vehicleCount"] += 1
    ordered = sorted(models.values(), key=lambda r: (r["brand"], r["modelId"]))
    selected = ordered[(body.page - 1) * body.pageSize:body.page * body.pageSize]
    return dict(brand=sorted({r["brand"] for r in selected}), vehicle=selected,
        tier=[tier_view(t, root["unit_code"]) for t in tiers], price=None,
        page=body.page, pageSize=body.pageSize, totalCount=len(ordered), hasNext=body.page * body.pageSize < len(ordered))


@router.post("/nadreego/vehicle/select")
def list_vehicles(body: Page, request: Request, session: Session = DB):
    from app.readmodels import fleet_details
    _, root = context(request, session)
    vehicles = fleet(request, session, root)
    ordered = sorted(vehicles, key=lambda k: (vehicles[k]["rental"]["model_id"], k))
    selected = {k: vehicles[k] for k in ordered[(body.page - 1) * body.pageSize:body.page * body.pageSize]}
    return page_result(fleet_details(request, session, root, selected), body.page, body.pageSize, len(vehicles))
