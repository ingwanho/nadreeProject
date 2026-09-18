from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.availability import reservation_end
from app.db import transaction
from app.headers import bearer
from app.pricing import daily_price, load_tiers
from app.rental_common import (OPEN, MOVABLE, context, contracts_for, day_end, effective_state, fleet,
    is_open, iso, local_date, midnight, page_result, resolve_spot, rows)
from app.rental_inputs import Calendar, Operations
from app.security import now
from app.vehicles import available_actions, vehicle_view

router = APIRouter(tags=["W07 Dashboard and calendar"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


def reservation_view(request, r, item):
    if not r:
        return None
    model = item["model"] if item else None
    return dict(reservationId=r["reservation_id"], startDatetime=iso(request, r["start_datetime"]),
        endDatetime=iso(request, r["end_datetime"]), requestedModelId=r["model_id"],
        requestedModelName=model["model_name"] if model else None, assignedVehicleId=r["assigned_vehicle_id"],
        assignedVehicleNo=(item["rental"]["plate_number_full"] or item["vehicle"]["plate_number"]) if item else None,
        assignmentStatus=r["vehicle_assignment_status"])


def rental_view(request, c):
    return dict(rentalContractId=c["rental_contract_id"], actualStartTime=iso(request, c["actual_start_time"]),
        actualEndTime=iso(request, c["actual_end_time"]), contractStatus=c["contract_status"],
        plannedEndDate=c["planned_end_date"]) if c else None


def record_actions(reservation, contract, sensor=False):
    if contract:
        if is_open(contract):
            return ["RETURN"] + (["LOCATION"] if sensor else [])
        return []
    if reservation["reservation_status"] == "REQUESTED":
        return ["APPROVE", "REJECT"]
    if reservation["reservation_status"] == "APPROVED":
        return ["RENT_APPROVE", "CANCEL"]
    return []


def fleet_details(request, session, root, vehicles):
    db = request.app.state.db
    t = db.table("MSP_RENTAL_CONTRACT")
    contracts = rows(session, t, t.c.vehicle_id.in_(vehicles), t.c.contract_status.in_(OPEN), t.c.actual_end_time.is_(None)) if vehicles else []
    r = db.table("MSP_RESERVATION")
    reservations = rows(session, r, r.c.spot_master_id == root["spot_master_id"], r.c.assigned_vehicle_id.in_(vehicles),
        r.c.reservation_status.in_(["REQUESTED", "APPROVED", "HANDED_OVER"])) if vehicles else []
    tiers = load_tiers(request, session, root["spot_master_id"])
    items = []
    for ident, item in vehicles.items():
        active = [c for c in contracts if c["vehicle_id"] == ident]
        active.sort(key=lambda c: c["rental_contract_id"])
        contract = active[0] if len(active) == 1 else None
        bookings = [b for b in reservations if b["assigned_vehicle_id"] == ident and
                    (b["reservation_status"] == "HANDED_OVER" or reservation_end(request, b) > now())]
        bookings.sort(key=lambda b: (b["reservation_id"] != (contract or {}).get("reservation_id"), b["reservation_status"] == "REQUESTED", b["start_datetime"]))
        booking = bookings[0] if bookings else None
        state = effective_state(request, item, contracts)
        current_booking = None if not booking else dict(bookedNo="BO" + booking["reservation_id"],
            reservationStatus=booking["reservation_status"], assignmentStatus=booking["vehicle_assignment_status"],
            startDatetime=iso(request, booking["start_datetime"]), endDatetime=iso(request, booking["end_datetime"]))
        current_rental = rental_view(request, contract)
        if current_rental:
            current_rental["bookedNo"] = "BO" + contract["reservation_id"] if contract["reservation_id"] else "RT" + contract["rental_contract_id"]
        qr = item["qr"]
        qr_state = qr["qr_status"] if qr else None
        if qr and qr["expired_at"] is not None and qr["expired_at"] <= now():
            qr_state = "EXPIRED"
        items.append(dict(vehicle=vehicle_view(request, item, contracts), modelImageKey=(item["model"] or {}).get("model_image_key"),
            registrationType="SENSOR" if item["sensors"] else "QR_ONLY", qrStatus=qr_state,
            sensorStatus="LINKED" if len(item["sensors"]) == 1 else "ERROR" if item["sensors"] else "UNLINKED",
            priceType=item["rental"]["price_type"], priceInfo=item["rental"]["premium_daily_price"], dailyPrice=daily_price(item, tiers),
            vehicleStatus=state, currentBooking=current_booking, currentRental=current_rental,
            maintenance=dict(maintenanceUntil=item["state"]["maintenance_until"], reason=item["state"]["status_reason"]) if state == "MAINTENANCE" else None,
            availableActions=available_actions(request, item, contracts)))
    return items


def operation_query(request, root):
    db = request.app.state.db
    r, c = db.table("MSP_RESERVATION"), db.table("MSP_RENTAL_CONTRACT")
    with_contract = c.c.rental_contract_id.is_not(None)
    common = [c.c.rental_contract_id, c.c.contract_status, c.c.actual_end_time, c.c.planned_end_date]
    booked = select((literal("BO") + r.c.reservation_id).label("booked_no"), r.c.reservation_id, *common,
        r.c.reservation_status, case((with_contract, literal("RENTAL")), else_=literal("RESERVATION")).label("record_type"),
        case((with_contract, c.c.vehicle_id), else_=r.c.assigned_vehicle_id).label("vehicle_id"),
        case((with_contract, c.c.uid_token), else_=r.c.uid_token).label("uid_token"),
        case((with_contract, c.c.actual_start_time), else_=r.c.start_datetime).label("begin"),
        r.c.end_datetime.label("reservation_end"))
    booked = booked.select_from(r.outerjoin(c, c.c.reservation_id == r.c.reservation_id)).where(r.c.spot_master_id == root["spot_master_id"])
    walkin = select((literal("RT") + c.c.rental_contract_id).label("booked_no"), c.c.reservation_id, *common,
        literal(None).label("reservation_status"), literal("RENTAL").label("record_type"), c.c.vehicle_id, c.c.uid_token,
        c.c.actual_start_time.label("begin"), literal(None).label("reservation_end")).where(
            c.c.reservation_id.is_(None), c.c.pickup_spot_master_id == root["spot_master_id"])
    return union_all(booked, walkin).subquery("operations")


def filtered_operations(request, root, body):
    db = request.app.state.db
    base = operation_query(request, root)
    u, v, rv = (db.table(n) for n in ("MSP_RENTAL_USER", "MSP_VEHICLE", "MSP_RENTAL_VEHICLE"))
    source = base.outerjoin(u, u.c.uid_token == base.c.uid_token).outerjoin(v, v.c.vehicle_id == base.c.vehicle_id).outerjoin(rv, rv.c.vehicle_id == base.c.vehicle_id)
    condition = literal(True)
    for key, value in [("record_type", body.recordType), ("reservation_status", body.reservationStatus), ("contract_status", body.rentalStatus)]:
        if value:
            condition &= base.c[key] == value
    keyword = (body.keyword or "").strip().lower()
    if keyword:
        condition &= or_(*[func.lower(column).contains(keyword, autoescape=True) for column in
                           (base.c.booked_no, u.c.name, func.coalesce(rv.c.plate_number_full, v.c.plate_number))])
    if body.startDate:
        begin, end = midnight(request, body.startDate), day_end(request, body.endDate)
        rental = base.c.rental_contract_id.is_not(None)
        unreturned = base.c.actual_end_time.is_(None)
        overdue = and_(base.c.contract_status.in_(OPEN), unreturned,
                       or_(base.c.contract_status == "OVERDUE", base.c.planned_end_date < local_date(request, now()), base.c.planned_end_date.is_(None)))
        condition &= (base.c.begin < end) & or_(
            and_(~rental, base.c.reservation_end >= begin),
            and_(rental, base.c.actual_end_time > begin),
            and_(rental, unreturned, base.c.planned_end_date >= body.startDate), overdue)
    return base, source, condition


def masked_phone(value):
    if not value:
        return None
    digits = "".join(c for c in value if c.isdigit())
    return "***" + digits[-4:] if len(digits) >= 4 else None


def masked_address(value):
    if not value:
        return None
    return " ".join(value.split()[:2]) + " ***"


def operation_details(request, session, root, records):
    if not records:
        return []
    db = request.app.state.db
    rids = {x["reservation_id"] for x in records if x["reservation_id"]}
    cids = {x["rental_contract_id"] for x in records if x["rental_contract_id"]}
    vids = {x["vehicle_id"] for x in records if x["vehicle_id"]}
    uids = {x["uid_token"] for x in records}

    def mapped(name, key, ids):
        t = db.table(name)
        return {r[key]: r for r in rows(session, t, t.c[key].in_(ids))} if ids else {}

    reservations = mapped("MSP_RESERVATION", "reservation_id", rids)
    contracts = mapped("MSP_RENTAL_CONTRACT", "rental_contract_id", cids)
    users = mapped("MSP_RENTAL_USER", "uid_token", uids)
    vehicles = mapped("MSP_VEHICLE", "vehicle_id", vids)
    extras = mapped("MSP_RENTAL_VEHICLE", "vehicle_id", vids)
    states = mapped("MSP_VEHICLE_STATUS", "vehicle_id", vids)
    models = mapped("MSP_VEHICLE_MODEL", "model_id", {x["model_id"] for x in extras.values()} | {x["model_id"] for x in reservations.values()})
    regions = mapped("MSP_DELIVERY_REGION", "delivery_region_id", {r["delivery_region_id"] for r in reservations.values() if r["delivery_region_id"]})
    sr = db.table("MSP_SPOT_RENT")
    spot_rent = session.execute(select(sr).where(sr.c.spot_master_id == root["spot_master_id"])).mappings().first()
    s = db.table("MSP_SENSOR")
    sensors = rows(session, s, s.c.vehicle_id.in_(vids), s.c.is_active == 1) if vids else []
    p = db.table("MSP_RENTAL_PAYMENT")
    payments = rows(session, p, p.c.payment_environment == request.app.state.settings.paypal_environment,
                    or_(p.c.reservation_id.in_(rids), p.c.rental_contract_id.in_(cids)))
    payments.sort(key=lambda p: (p["paid_at"] is not None, p["created_at"], p["payment_id"]), reverse=True)
    histories = []
    for name, ids, key, kind in [("MSP_RESERVATION_HISTORY", rids, "reservation_id", "RESERVATION"),
                                 ("MSP_RENTAL_CONTRACT_HISTORY", cids, "rental_contract_id", "RENTAL")]:
        table = db.table(name)
        # Window rank avoids loading every historical event for each page.
        ranked = select(table, func.row_number().over(partition_by=table.c[key],
            order_by=[table.c.created_at.desc(), table.c.history_id.desc()]).label("rn")).where(table.c[key].in_(ids)).subquery()
        histories.extend({**dict(h), "kind": kind} for h in session.execute(select(ranked).where(ranked.c.rn == 1)).mappings())
    histories.sort(key=lambda h: (h["created_at"], h["kind"] == "RENTAL", h["history_id"]), reverse=True)
    e = db.table("MSP_PAYPAL_WEBHOOK_EVENT")
    ranked = select(e.c.payment_id, e.c.event_type, func.row_number().over(partition_by=e.c.payment_id,
        order_by=[e.c.processed_at.desc(), e.c.webhook_event_id.desc()]).label("rn")).where(
        e.c.payment_id.in_([p["payment_id"] for p in payments]), e.c.processing_status == "PROCESSED").subquery()
    last_events = {e["payment_id"]: e["event_type"] for e in session.execute(select(ranked).where(ranked.c.rn == 1)).mappings()}
    result = []
    for rec in records:
        r, c = reservations.get(rec["reservation_id"]), contracts.get(rec["rental_contract_id"])
        vid, rid, cid = rec["vehicle_id"], rec["reservation_id"], rec["rental_contract_id"]
        user = users.get(rec["uid_token"])
        item = None
        if vid in vehicles and vid in extras:
            item = dict(vehicle=vehicles[vid], rental=extras[vid], model=models.get(extras[vid]["model_id"]), state=states.get(vid))
        vehicle = vehicle_view(request, item, list(contracts.values())) if item else {}
        reservation = reservation_view(request, r, item)
        if reservation:
            reservation["requestedModelName"] = (models.get(r["model_id"]) or {}).get("model_name")
        payment = next((p for p in payments if rid and p["reservation_id"] == rid or cid and p["rental_contract_id"] == cid), None)
        payment_view = None
        if payment:
            payment_view = {target: payment[key] for key, target in [("payment_id", "paymentId"), ("payment_provider", "paymentProvider"),
                ("payment_environment", "paymentEnvironment"), ("payment_status", "paymentStatus"), ("paypal_order_id", "paypalOrderId"),
                ("paypal_capture_id", "paypalCaptureId"), ("currency", "currency"), ("refund_status", "refundStatus"),
                ("paypal_refund_id", "paypalRefundId")]}
            payment_view.update(totalPrice=float(payment["total_price"]), refundedAmount=float(payment["refunded_amount"]),
                paidAt=iso(request, payment["paid_at"]), updatedAt=iso(request, payment["updated_at"]), lastWebhookEventType=last_events.get(payment["payment_id"]))
        history = next((h for h in histories if rid and h.get("reservation_id") == rid or cid and h.get("rental_contract_id") == cid), None)
        history_view = None
        if history:
            prefix = "contract" if history["kind"] == "RENTAL" else "reservation"
            history_view = dict(historyId=history["history_id"], historyType=history["kind"], reservationId=rid, rentalContractId=cid,
                actionType=history["event_type"], fromStatus=history["previous_" + prefix + "_status"], toStatus=history["new_" + prefix + "_status"],
                reason=history["reason"], changedBy=history["changed_by"], changedAt=iso(request, history["created_at"]))
        delivery = None
        if r:
            delivery = dict(deliveryRequestType=r["delivery_request_type"], deliveryRegionId=r["delivery_region_id"],
                regionName=(regions.get(r["delivery_region_id"]) or {}).get("region_name"),
                startAddress=masked_address(r["delivery_start_address"]), returnAddress=masked_address(r["delivery_return_address"]),
                spotDeliveryServiceType=spot_rent["delivery_service_type"] if spot_rent else "NONE",
                startDeliveryFee=r["start_delivery_fee_snapshot"], returnDeliveryFee=r["return_delivery_fee_snapshot"],
                deliveryTotalFee=r["delivery_total_fee_snapshot"])
        result.append(dict(bookedNo=rec["booked_no"], recordType=rec["record_type"], reservationStatus=rec["reservation_status"],
            rentalStatus=rec["contract_status"], user=dict(userId=user["uid_token"], name=user["name"], phone=None,
            gender=user["gender"], age=user["age"], nationality=user["nationality"]) if user else {}, reservation=reservation, rental=rental_view(request, c),
            vehicle=vehicle, payment=payment_view, delivery=delivery, latestHistory=history_view,
            availableActions=record_actions(r, c, len([s for s in sensors if s["vehicle_id"] == vid]) == 1)))
    return result


@router.post("/nadreego/booking/select")
def operations(body: Operations, request: Request, session: Session = DB):
    _, root = context(request, session)
    base, source, where = filtered_operations(request, root, body)
    total = session.scalar(select(func.count()).select_from(source).where(where))
    records = session.execute(select(base).select_from(source).where(where).order_by(base.c.begin.is_(None),
        base.c.begin.desc(), base.c.booked_no).offset((body.page - 1) * body.pageSize).limit(body.pageSize)).mappings().all()
    return page_result(operation_details(request, session, root, records), body.page, body.pageSize, total)


@router.post("/nadreego/main/calendar")
def calendar(body: Calendar, request: Request, session: Session = DB):
    _, root = context(request, session)
    spot = resolve_spot(request, session, root, body.spotCode)
    at = now()
    begin, end = midnight(request, body.startDate), midnight(request, body.endDate)
    vehicles = fleet(request, session, spot, model_id=body.modelId)
    db = request.app.state.db
    ct = db.table("MSP_RENTAL_CONTRACT")
    contracts = rows(session, ct, ct.c.vehicle_id.in_(vehicles), ct.c.pickup_spot_master_id == spot["spot_master_id"]) if vehicles else []
    keyword = (body.keyword or "").strip().casefold()
    selected = []
    for ident, item in vehicles.items():
        view = vehicle_view(request, item, contracts)
        if body.vehicleStatus and view["vehicleStatus"] != body.vehicleStatus:
            continue
        if keyword and not any(keyword in str(view.get(key) or "").casefold() for key in ("vehicleNo", "modelName")):
            continue
        selected.append(ident)
    selected.sort(key=lambda k: (vehicles[k]["rental"]["model_id"], k))
    total = len(selected)
    selected = selected[(body.page - 1) * body.pageSize:body.page * body.pageSize]
    rt = db.table("MSP_RESERVATION")
    conditions = [rt.c.spot_master_id == spot["spot_master_id"], rt.c.start_datetime < end,
                  rt.c.reservation_status.in_(["REQUESTED", "APPROVED", "HANDED_OVER", "RETURNED"])]
    if body.modelId:
        conditions.append(rt.c.model_id == body.modelId)
    reservations = rows(session, rt, *conditions)
    events, warnings = defaultdict(list), []
    by_reservation = {c["reservation_id"]: c for c in contracts if c["reservation_id"]}

    def warning(code, vehicle=None, booked=None):
        warnings.append(dict(code=code, vehicleId=vehicle, bookedNo=booked, message=code))

    def add_event(ident, key, kind, rid, cid, start, finish, end_type, state, assignment, blocking, reassign, actions, updated, opened=False):
        if ident not in selected or start is None or start >= end or (finish is not None and finish <= begin and not opened):
            return
        events[ident].append(dict(eventId=key, eventType=kind, bookedNo=key if kind != "MAINTENANCE" else None,
            reservationId=rid, rentalContractId=cid, startAt=iso(request, start), endAt=iso(request, finish), endAtType=end_type,
            status=state, assignmentStatus=assignment, isBlocking=blocking, canReassign=reassign,
            availableActions=actions, updatedAt=iso(request, updated)))

    for r in reservations:
        key, ident = "BO" + r["reservation_id"], r["assigned_vehicle_id"]
        c = by_reservation.get(r["reservation_id"])
        if c:
            expected = "RETURNED" if c["contract_status"] == "RETURNED" else "HANDED_OVER"
            if r["reservation_status"] != expected and c["vehicle_id"] in selected:
                warning("RENTAL_STATE_INCONSISTENT", c["vehicle_id"], key)
            continue
        if r["reservation_status"] in ("HANDED_OVER", "RETURNED"):
            if ident in selected:
                warning("RENTAL_STATE_INCONSISTENT", ident, key)
            continue
        finish = reservation_end(request, r)
        if finish <= begin:
            continue
        if ident is None:
            warning("UNASSIGNED_RESERVATION", None, key)
        add_event(ident, key, "RESERVATION", r["reservation_id"], None, r["start_datetime"], finish, "PLANNED", r["reservation_status"],
            r["vehicle_assignment_status"], r["reservation_status"] == "APPROVED",
            r["vehicle_assignment_status"] in MOVABLE + ("SOFT_HOLD",), record_actions(r, None), r["updated_at"])
    for c in contracts:
        ident = c["vehicle_id"]
        if ident not in selected or c["contract_status"] == "CANCELED":
            continue
        key = "BO" + c["reservation_id"] if c["reservation_id"] else "RT" + c["rental_contract_id"]
        actual = c["actual_end_time"]
        finish = actual or (day_end(request, c["planned_end_date"]) if c["planned_end_date"] else None)
        if c["actual_start_time"] is None or finish is None:
            warning("RENTAL_PERIOD_UNAVAILABLE", ident, key)
        if c["contract_status"] == "RETURNED" and actual is None:
            warning("RENTAL_STATE_INCONSISTENT", ident, key)
        opened = is_open(c) and (finish is None or finish <= at or c["contract_status"] == "OVERDUE")
        add_event(ident, key, "RENTAL", c["reservation_id"], c["rental_contract_id"], c["actual_start_time"], finish,
            "ACTUAL" if actual else "PLANNED" if finish else "UNKNOWN", c["contract_status"], "RELEASED" if actual else "LOCKED", True, False,
            record_actions(None, c, len(vehicles[ident]["sensors"]) == 1), c["updated_at"], opened=opened)
    output = []
    for ident in selected:
        item = vehicles[ident]
        state = effective_state(request, item, contracts, at)
        s = item["state"]
        active = [c for c in contracts if c["vehicle_id"] == ident and is_open(c)]
        if s is None or len(active) > 1 or state == "ON_RENT" and not active or active and state != "ON_RENT":
            warning("RENTAL_STATE_INCONSISTENT", ident)
        if state == "MAINTENANCE":
            if s["maintenance_until"] is None:
                warning("RENTAL_STATE_INCONSISTENT", ident)
            else:
                add_event(ident, "MAINTENANCE:" + ident + ":" + iso(request, s["status_changed_at"]), "MAINTENANCE", None, None,
                    s["status_changed_at"], day_end(request, s["maintenance_until"]), "PLANNED", "MAINTENANCE", None,
                    True, False, ["REPAIR"], s["updated_at"])
        view = vehicle_view(request, item, contracts)
        events[ident].sort(key=lambda e: (e["startAt"], e["eventId"]))
        output.append({key: view[key] for key in ["vehicleId", "vehicleNo", "modelId", "modelName", "vehicleImageKey", "vehicleStatus"]} | {"events": events[ident]})
    return page_result(output, body.page, body.pageSize, total) | dict(startDate=body.startDate, endDate=body.endDate,
        timeZone=request.app.state.settings.business_timezone, fetchedAt=iso(request, at), warnings=warnings)


@router.get("/nadreego/main")
def dashboard(request: Request, session: Session = DB):
    actor, root = context(request, session)
    db = request.app.state.db
    r = db.table("MSP_RESERVATION")
    counts = dict(session.execute(select(r.c.reservation_status, func.count()).where(r.c.spot_master_id == root["spot_master_id"])
        .group_by(r.c.reservation_status)).all())
    today = local_date(request, now())
    base, source, where = filtered_operations(request, root, Operations(page=1, pageSize=100, startDate=today, endDate=today))
    records = session.execute(select(base).select_from(source).where(where).order_by(base.c.begin, base.c.booked_no)).mappings().all()
    work = [dict(bookedNo=r["booked_no"], recordType=r["record_type"], reservationStatus=r["reservation_status"],
                 rentalStatus=r["contract_status"], vehicleId=r["vehicle_id"], startAt=iso(request, r["begin"])) for r in records]
    vehicles = fleet(request, session, root)
    for ident, item in vehicles.items():
        s = item["state"]
        if s and s["status"] == "MAINTENANCE" and s["maintenance_until"] is not None and s["maintenance_until"] >= today:
            work.append(dict(vehicleId=ident, recordType="MAINTENANCE", maintenanceUntil=s["maintenance_until"]))
    return dict(status="success", group=dict(spotMasterId=root["spot_master_id"], spotCode=root["unit_code"], name=root["spot_name"]),
        name=actor.admin["admin_name"], totalVehicles=len(vehicles), totalReservations=counts.get("APPROVED", 0),
        pending=counts.get("REQUESTED", 0), chat=0, todayWork=work)
