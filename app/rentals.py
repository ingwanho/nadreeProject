import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.availability import (apply_assignments, compute_assignment, price_key, reservation_end,
                              reservation_history, reservation_price)
from app.db import transaction
from app.errors import Problem
from app.fcm import queue_reservation_decision
from app.headers import bearer
from app.pricing import daily_price, load_tiers
from app.paypal import execute_refund
from app.rental_common import (OPEN, action_result, context, contracts_for, day_end, effective_state,
                               expire_maintenance, fleet, is_open, iso, local_date, rows, verify_qr)
from app.rental_inputs import BookingAction, Qr, RentApprove
from app.security import now

router = APIRouter(tags=["W06 Reservations and rentals"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


def booking(request, session, root, booked_no):
    t = request.app.state.db.table("MSP_RESERVATION")
    row = session.execute(select(t).where(t.c.reservation_id == booked_no[2:],
        t.c.spot_master_id == root["spot_master_id"]).with_for_update()).mappings().first()
    if not row:
        raise Problem(404, "RESERVATION_NOT_FOUND")
    return dict(row)


def require_no_contract(request, session, reservation):
    t = request.app.state.db.table("MSP_RENTAL_CONTRACT")
    if session.execute(select(t.c.rental_contract_id).where(t.c.reservation_id == reservation["reservation_id"])).first():
        raise Problem(409, "RESERVATION_ALREADY_HANDED_OVER")


def customer(request, session, ident):
    db = request.app.state.db
    rental_user = db.table("MSP_RENTAL_USER")
    row = session.execute(select(rental_user).where(rental_user.c.uid_token == ident)).mappings().first()
    if row is None:
        raise Problem(404, "RENTAL_CUSTOMER_NOT_FOUND")
    return row


def paid_booking(request, session, reservation):
    t = request.app.state.db.table("MSP_RENTAL_PAYMENT")
    payments = session.execute(select(t).where(t.c.reservation_id == reservation["reservation_id"],
        t.c.payment_environment == request.app.state.settings.paypal_environment)
        .order_by(t.c.payment_id).with_for_update()).mappings().all()
    eligible = [p for p in payments if p["payment_status"] == "PAID" and p["paid_at"] is not None and
                p["paypal_capture_id"] and p["payment_provider"] == "PAYPAL" and p["refunded_amount"] == 0 and p["total_price"] > 0]
    if len(eligible) != 1:
        raise Problem(409, "PAYMENT_REQUIRED" if not eligible else "PAYMENT_STATE_INCONSISTENT")
    if eligible[0]["rental_contract_id"] is not None:
        raise Problem(409, "PAYMENT_ALREADY_LINKED")
    return eligible[0]


def prepare_booking_refund(request, session, reservation, actor, reason):
    payment_table = request.app.state.db.table("MSP_RENTAL_PAYMENT")
    payment = session.execute(select(payment_table).where(
        payment_table.c.reservation_id == reservation["reservation_id"],
        payment_table.c.payment_environment == request.app.state.settings.paypal_environment)
        .order_by(payment_table.c.payment_id.desc()).with_for_update()).mappings().first()
    if not payment:
        return None, None, False
    if payment["payment_provider"] != "PAYPAL":
        raise Problem(409, "PAYMENT_STATE_INCONSISTENT")
    status = payment["payment_status"]
    refund_status = payment.get("refund_status", "NONE")
    if status in ("PAID", "PARTIALLY_REFUNDED"):
        if not payment["paypal_capture_id"]:
            raise Problem(409, "PAYMENT_STATE_INCONSISTENT")
        if payment["refunded_amount"] >= payment["total_price"]:
            return payment["payment_id"], "COMPLETED", False
        if refund_status not in ("PENDING", "REQUESTED"):
            session.execute(update(payment_table).where(payment_table.c.payment_id == payment["payment_id"]).values(
                refund_status="REQUESTED", refund_requested_at=now(),
                refund_requested_by_admin_id=actor.admin["admin_id"], refund_reason=reason, updated_at=now()))
        return payment["payment_id"], "REQUESTED", True
    if status == "PENDING" and payment["paypal_capture_id"]:
        if refund_status not in ("PENDING", "REQUESTED"):
            session.execute(update(payment_table).where(payment_table.c.payment_id == payment["payment_id"]).values(
                refund_status="REQUESTED", refund_requested_at=now(),
                refund_requested_by_admin_id=actor.admin["admin_id"], refund_reason=reason, updated_at=now()))
        # Capture completion is handled by the corresponding webhook; PayPal
        # rejects a refund while the capture is still pending.
        return payment["payment_id"], "REQUESTED", False
    if status in ("CREATED", "PENDING"):
        session.execute(update(payment_table).where(payment_table.c.payment_id == payment["payment_id"]).values(
            payment_status="CANCELED", refund_status="NOT_REQUIRED", refund_reason=reason, updated_at=now()))
        return payment["payment_id"], "NOT_REQUIRED", False
    return payment["payment_id"], refund_status, False


def contract_history(request, session, ident, previous, new, actor, event):
    t = request.app.state.db.table("MSP_RENTAL_CONTRACT_HISTORY")
    session.execute(t.insert().values(rental_contract_id=ident, event_type=event,
        previous_contract_status=previous, new_contract_status=new, changed_by=actor, created_at=now()))


@router.post("/nadreego/booking/action")
def booking_action(body: BookingAction, request: Request, background_tasks: BackgroundTasks, session: Session = DB):
    actor, root = context(request, session, write=True)
    r = booking(request, session, root, body.bookedNo)
    expected = "APPROVED" if body.action == "CANCEL" else "REQUESTED"
    if r["reservation_status"] != expected:
        raise Problem(409, "RESERVATION_STATE_INVALID")
    require_no_contract(request, session, r)
    refund_payment_id, refund_status, refund_ready = (None, None, False)
    if body.action == "CANCEL":
        refund_payment_id, refund_status, refund_ready = prepare_booking_refund(request, session, r, actor, body.reason)
    values = dict(updated_at=now())
    if body.action == "APPROVE":
        if reservation_end(request, r) <= now():
            raise Problem(409, "RESERVATION_PERIOD_ENDED")
        customer(request, session, r["uid_token"])
        vehicles = fleet(request, session, root, model_id=r["model_id"], lock=True)
        if not vehicles:
            raise Problem(409, "VEHICLE_UNAVAILABLE")
        contracts = contracts_for(request, session, list(vehicles))
        expire_maintenance(request, session, vehicles, contracts)
        assignment, records = compute_assignment(request, session, root, vehicles, contracts, candidate=r)
        apply_assignments(request, session, assignment, records, actor.admin["admin_id"], skip=r["reservation_id"])
        values.update(reservation_status="APPROVED", vehicle_assignment_status="PROVISIONAL",
                      assigned_vehicle_id=assignment[r["reservation_id"]], vehicle_assigned_at=now())
        # Existing JSON stores the accepted price without adding a column or changing settled payments.
        criteria = dict(r["required_criteria_json"] or {})
        kind, price = reservation_price(r, vehicles, load_tiers(request, session, root["spot_master_id"]))
        criteria.update(priceType=kind, dailyPrice=price)
        values["required_criteria_json"] = criteria
        event = "APPROVED"
    else:
        values.update(reservation_status="CANCELED" if body.action == "CANCEL" else "REJECTED",
                      vehicle_assignment_status="RELEASED", assigned_vehicle_id=None, vehicle_assigned_at=None)
        event = "CANCELLED" if body.action == "CANCEL" else "REJECTED"
    table = request.app.state.db.table("MSP_RESERVATION")
    session.execute(update(table).where(table.c.reservation_id == r["reservation_id"]).values(**values))
    reservation_history(request, session, r, values, event, actor.admin["admin_id"], body.reason)
    if body.action in ("APPROVE", "REJECT"):
        queue_reservation_decision(request.app.state.db, session, r["uid_token"],
                                   r["reservation_id"], values["reservation_status"])
    if refund_payment_id and refund_status == "REQUESTED" and refund_ready:
        background_tasks.add_task(execute_refund, request.app.state.db, request.app.state.paypal, refund_payment_id)
    data = dict(bookedNo=body.bookedNo, reservationStatus=values["reservation_status"],
                vehicleAssignmentStatus=values["vehicle_assignment_status"])
    if refund_status is not None:
        data["refundStatus"] = refund_status
    return action_result(request, actor, values["reservation_status"], data)


@router.post("/nadreego/rent/approve")
def approve_rent(body: RentApprove, request: Request, session: Session = DB):
    actor, root = context(request, session, write=True)
    qr = verify_qr(request, session, root, body.qrCode.get_secret_value(), lock=True)
    db = request.app.state.db
    rv = db.table("MSP_RENTAL_VEHICLE")
    model = session.scalar(select(rv.c.model_id).where(rv.c.vehicle_id == qr["vehicle_id"]))
    if model is None:
        raise Problem(409, "RENTAL_VEHICLE_NOT_CONFIGURED")
    vehicles = fleet(request, session, root, model_id=model, lock=True)
    item = vehicles.get(qr["vehicle_id"])
    if item is None:
        raise Problem(404, "VEHICLE_NOT_FOUND")
    contracts = contracts_for(request, session, list(vehicles))
    if any(c["vehicle_id"] == qr["vehicle_id"] and is_open(c) for c in contracts):
        raise Problem(409, "VEHICLE_ALREADY_ON_RENT")
    expire_maintenance(request, session, vehicles, contracts)
    if effective_state(request, item, contracts) != "AVAILABLE" or not item["vehicle"]["is_active"] or not item["rental"]["rental_enabled"] or not item["model"] or not item["model"]["is_active"]:
        raise Problem(409, "VEHICLE_UNAVAILABLE")
    if len(item["sensors"]) > 1:
        raise Problem(409, "SENSOR_STATE_INCONSISTENT")
    tiers = load_tiers(request, session, root["spot_master_id"])
    if daily_price(item, tiers) is None:
        raise Problem(409, "PRICE_NOT_CONFIGURED")
    r, payment = None, None
    at = now()
    if body.bookedNo:
        r = booking(request, session, root, body.bookedNo)
        if r["reservation_status"] != "APPROVED":
            raise Problem(409, "RESERVATION_NOT_APPROVED")
        require_no_contract(request, session, r)
        if r["model_id"] != model or reservation_price(r, vehicles, tiers) != price_key(item, tiers):
            raise Problem(409, "RESERVATION_VEHICLE_MISMATCH")
        if r["vehicle_assignment_status"] == "LOCKED" and r["assigned_vehicle_id"] != qr["vehicle_id"]:
            raise Problem(409, "VEHICLE_ASSIGNMENT_LOCKED")
        if r["vehicle_assignment_status"] not in ("PROVISIONAL", "REALLOCATED", "LOCKED"):
            raise Problem(409, "RESERVATION_ASSIGNMENT_INVALID")
        if at < r["start_datetime"] or at >= reservation_end(request, r):
            raise Problem(409, "OUTSIDE_RESERVATION_PERIOD")
        uid_token = r["uid_token"]
        end_date = local_date(request, r["end_datetime"])
        payment = paid_booking(request, session, r)
    else:
        uid_token, end_date = body.uidToken, body.plannedEndDate
    customer(request, session, uid_token)
    if end_date < local_date(request, at):
        raise Problem(400, "PLANNED_END_DATE_INVALID")
    assignment, records = compute_assignment(request, session, root, vehicles, contracts,
        checkout=(qr["vehicle_id"], at, day_end(request, end_date)), omit_reservation=r["reservation_id"] if r else None)
    apply_assignments(request, session, assignment, records, actor.admin["admin_id"])
    ident = str(uuid.uuid4())
    t, state = db.table("MSP_RENTAL_CONTRACT"), db.table("MSP_VEHICLE_STATUS")
    session.execute(t.insert().values(rental_contract_id=ident, reservation_id=r["reservation_id"] if r else None,
        vehicle_id=qr["vehicle_id"], uid_token=uid_token, sensor_id=item["sensors"][0]["sensor_id"] if item["sensors"] else None,
        pickup_spot_master_id=root["spot_master_id"], actual_start_time=at, planned_end_date=end_date,
        contract_status="ON_RENT", created_at=at, updated_at=at))
    session.execute(update(state).where(state.c.vehicle_id == qr["vehicle_id"]).values(status="ON_RENT",
        maintenance_until=None, status_reason=None, status_changed_at=at, changed_by=actor.admin["admin_id"], updated_at=at))
    if r:
        reservation = db.table("MSP_RESERVATION")
        values = dict(reservation_status="HANDED_OVER", assigned_vehicle_id=qr["vehicle_id"],
                      vehicle_assignment_status="LOCKED", vehicle_assigned_at=at, updated_at=at)
        session.execute(update(reservation).where(reservation.c.reservation_id == r["reservation_id"]).values(**values))
        reservation_history(request, session, r, values, "HANDED_OVER", actor.admin["admin_id"])
        pt = db.table("MSP_RENTAL_PAYMENT")
        session.execute(update(pt).where(pt.c.reservation_id == r["reservation_id"], pt.c.rental_contract_id.is_(None))
            .values(rental_contract_id=ident, updated_at=at))
    contract_history(request, session, ident, None, "ON_RENT", actor.admin["admin_id"], "STARTED")
    return action_result(request, actor, "ON_RENT", dict(bookedNo=body.bookedNo or "RT" + ident,
        rentalContractId=ident, contractStatus="ON_RENT", vehicleStatus="ON_RENT", plannedEndDate=end_date,
        reservationStatus="HANDED_OVER" if r else None, vehicleAssignmentStatus="LOCKED" if r else None))


@router.post("/nadreego/vehicle/return")
def return_vehicle(body: Qr, request: Request, session: Session = DB):
    actor, root = context(request, session, write=True)
    qr = verify_qr(request, session, root, body.qrCode.get_secret_value(), lock=True)
    db = request.app.state.db
    t = db.table("MSP_RENTAL_CONTRACT")
    found = session.execute(select(t).where(t.c.vehicle_id == qr["vehicle_id"],
        t.c.contract_status.in_(OPEN), t.c.actual_end_time.is_(None)).with_for_update()).mappings().all()
    if len(found) != 1:
        raise Problem(404 if not found else 409, "RENTAL_NOT_FOUND" if not found else "RENTAL_STATE_INCONSISTENT")
    contract = found[0]
    if contract["pickup_spot_master_id"] != root["spot_master_id"] or contract["actual_start_time"] is None:
        raise Problem(409, "RENTAL_STATE_INCONSISTENT")
    state = db.table("MSP_VEHICLE_STATUS")
    current = session.scalar(select(state.c.status).where(state.c.vehicle_id == qr["vehicle_id"]))
    if current != "ON_RENT":
        raise Problem(409, "RENTAL_STATE_INCONSISTENT")
    r = None
    if contract["reservation_id"]:
        r = booking(request, session, root, "BO" + contract["reservation_id"])
        if r["reservation_status"] != "HANDED_OVER" or r["assigned_vehicle_id"] != qr["vehicle_id"] or r["vehicle_assignment_status"] != "LOCKED":
            raise Problem(409, "RENTAL_STATE_INCONSISTENT")
    at = now()
    if contract["actual_start_time"] > at:
        raise Problem(409, "RENTAL_STATE_INCONSISTENT")
    session.execute(update(t).where(t.c.rental_contract_id == contract["rental_contract_id"]).values(
        contract_status="RETURNED", actual_end_time=at, return_spot_master_id=root["spot_master_id"], updated_at=at))
    session.execute(update(state).where(state.c.vehicle_id == qr["vehicle_id"]).values(status="AVAILABLE",
        maintenance_until=None, status_reason=None, status_changed_at=at, changed_by=actor.admin["admin_id"], updated_at=at))
    if r:
        reservation = db.table("MSP_RESERVATION")
        values = dict(reservation_status="RETURNED", vehicle_assignment_status="RELEASED", updated_at=at)
        session.execute(update(reservation).where(reservation.c.reservation_id == r["reservation_id"]).values(**values))
        reservation_history(request, session, r, values, "RETURNED", actor.admin["admin_id"])
    contract_history(request, session, contract["rental_contract_id"], contract["contract_status"], "RETURNED", actor.admin["admin_id"], "RETURNED")
    return action_result(request, actor, "RETURNED", dict(rentalContractId=contract["rental_contract_id"], actualEndTime=iso(request, at),
        vehicleStatus="AVAILABLE", reservationStatus="RETURNED" if r else None, vehicleAssignmentStatus="RELEASED" if r else None))
