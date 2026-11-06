"""Authenticated, shared-QR onsite requests and explicit customer receipt."""
import uuid
import hmac
from datetime import date, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, SecretStr
from sqlalchemy import select

from app.availability import compute_assignment, price_key, reservation_history
from app.customer_rentals import (_model_view, _price_view, _spot, _spot_view, customer_access_token,
                                  nadree_reservation_detail)
from app.db import request_transaction, transaction
from app.errors import Problem
from app.fcm import queue_reservation_request
from app.pricing import load_tiers
from app.receipt import PENDING, hold_reason, require_schema, view
from app.reservation_payments import EXTERNAL
from app.responses import CustomerOnsiteQuote, CustomerOnsiteResult, CustomerQrLookup, CustomerReservationDetail
from app import onsite_requests as outcomes
from app.rental_common import (contracts_for, day_end, fleet, iso, local_date, location_snapshot,
                               lock_key, qr_digest, verify_qr)
from app.rental_inputs import Qr
from app.rentals import check_handover_vehicle, paid_booking, start_contract
from app.schemas import Body
from app.security import now, user_principal

router = APIRouter(prefix="/api/v1/nadree/rental", tags=["Nadree customer rentals"],
                   dependencies=[Depends(customer_access_token)])
DB = Depends(transaction, scope="function")
REQUEST_DB = Depends(request_transaction, scope="function")
RequestKey = Annotated[str, Field(min_length=16, max_length=64, pattern=r"^[a-z0-9_-]+$")]


class Lookup(Qr):
    reservationId: str | None = Field(default=None, min_length=1, max_length=50)


class Quote(Qr):
    returnDate: date


class OnsiteRequest(Quote):
    clientRequestId: RequestKey
    quoteToken: SecretStr = Field(min_length=1, max_length=8192)


def resolve(request, session, raw, *, lock=False):
    """No lowercase, strip, URL opening, or fragment guessing on the backend."""
    db = request.app.state.db
    qr, membership = db.table("MSP_VEHICLE_QR"), db.table("MSP_VEHICLE_SPOT_HISTORY")
    record = session.execute(select(qr).where(qr.c.qr_code_hash == qr_digest(request, raw))).mappings().first()
    if not record:
        raise Problem(404, "QR_NOT_FOUND")
    spots = list(session.scalars(select(membership.c.spot_master_id).where(
        membership.c.vehicle_id == record["vehicle_id"], membership.c.released_at.is_(None))))
    if len(spots) != 1:
        raise Problem(409, "QR_STATE_INCONSISTENT")
    if lock:
        master = db.table("MSP_SPOT_MASTER")
        session.execute(select(master.c.spot_master_id).where(master.c.spot_master_id == spots[0]).with_for_update()).first()
    spot = _spot(request, session, spots[0])
    verify_qr(request, session, spot, raw, lock=lock)
    vehicles = fleet(request, session, spot, vehicle_ids=[record["vehicle_id"]])
    item = vehicles.get(record["vehicle_id"])
    if not item or not item["vehicle"]["is_active"] or not item["rental"]["rental_enabled"] or not item["model"] or not item["model"]["is_active"]:
        raise Problem(409, "VEHICLE_UNAVAILABLE")
    return spot, item


def limited(request, uid):
    request.app.state.limiter.check("customer-qr:" + uid, limit=30, seconds=60)


@router.post("/qr/lookup", response_model=CustomerQrLookup, summary="공용 QR 원문으로 차량·본인 예약 조회")
def lookup(body: Lookup, request: Request, session=DB):
    user = user_principal(request, session)
    limited(request, user.uid_token)
    db = request.app.state.db
    r = db.table("MSP_RESERVATION")
    own = None
    if body.reservationId:
        own = session.execute(select(r).where(r.c.reservation_id == body.reservationId,
            r.c.uid_token == user.uid_token)).mappings().first()
        if not own:
            raise Problem(404, "RESERVATION_NOT_FOUND")
    require_schema(db)
    spot, item = resolve(request, session, body.qrCode.get_secret_value())
    vehicle = item["vehicle"]["vehicle_id"]
    def matches(row):
        criteria = row.get("required_criteria_json") or {}
        return (row["assigned_vehicle_id"] == vehicle or criteria.get("onsiteVehicleId") == vehicle
                or not row["assigned_vehicle_id"] and row["model_id"] == item["rental"]["model_id"]
                   and row["spot_master_id"] == spot["spot_master_id"])
    if own and not matches(own):
        raise Problem(409, "RESERVATION_VEHICLE_MISMATCH")
    if not own:
        candidates = list(session.execute(select(r).where(r.c.uid_token == user.uid_token,
            r.c.reservation_status.in_(("REQUESTED", "APPROVED", PENDING, "HANDED_OVER")))).mappings())
        candidates = [row for row in candidates if matches(row)]
        if len(candidates) > 1:
            raise Problem(409, "RESERVATION_SELECTION_REQUIRED")
        own = candidates[0] if candidates else None
    actions = []
    if own:
        state = own["reservation_status"]
        actions = ["CONFIRM_RECEIPT"] if view(request, own)["canReceive"] else ["WAIT_APPROVAL"] if state == "REQUESTED" else ["WAIT_HANDOVER"] if state == "APPROVED" else []
    elif (item["state"] or {}).get("status") == "AVAILABLE":
        actions = ["ONSITE_QUOTE"]
    contract = next((c for c in contracts_for(request, session, [vehicle])
                     if own and c["reservation_id"] == own["reservation_id"]), None) if own else None
    return {"status": "success", "vehicleId": vehicle,
            "vehicleNo": item["rental"]["plate_number_full"] or item["vehicle"].get("plate_number"),
            "vehicleStatus": (item["state"] or {}).get("status"), "model": _model_view(item["model"]),
            "spot": _spot_view(spot), "reservationId": own["reservation_id"] if own else None,
            "reservationStatus": own["reservation_status"] if own else None,
            "vehicleMatch": "ASSIGNED" if own and own["assigned_vehicle_id"] == vehicle else "MODEL_PENDING" if own else None,
            **view(request, own, contract), "availableActions": actions}


def plan(request, session, spot, item, return_date):
    today = local_date(request, now())
    if not today < return_date <= today + timedelta(days=30):
        raise Problem(422, "INVALID_ONSITE_PERIOD")
    tiers = load_tiers(request, session, spot["spot_master_id"])
    vehicles = fleet(request, session, spot, model_id=item["rental"]["model_id"])
    contracts = contracts_for(request, session, list(vehicles))
    check_handover_vehicle(request, item, contracts, tiers)
    if location_snapshot(spot) is None:
        raise Problem(409, "SHOP_LOCATION_REQUIRED")
    kind, daily = price_key(item, tiers)
    candidate = dict(reservation_id="onsite-quote", model_id=item["rental"]["model_id"],
        assigned_vehicle_id=item["vehicle"]["vehicle_id"], vehicle_assignment_status="LOCKED",
        start_datetime=now(), end_datetime=day_end(request, return_date) - timedelta(seconds=1),
        required_criteria_json={"priceType": kind, "dailyPrice": daily})
    compute_assignment(request, session, spot, vehicles, contracts, candidate=candidate)
    delivery = dict(deliveryStartFee=0, deliveryReturnFee=0, deliveryTotalFee=0)
    request._nadri_session, request._nadri_spot = session, spot
    price = _price_view(request, {(kind, daily)}, today, return_date, delivery, model=item["model"])
    price.update(requestedTotal=price["totalFrom"], finalTotal=price["totalFrom"])
    return candidate, price


def quote_key(request):
    key = request.app.state.settings.jwt_secret.get_secret_value()
    if len(key.encode()) < 32:
        raise Problem(503, "AUTH_NOT_CONFIGURED")
    return key


@router.post("/onsite/quote", response_model=CustomerOnsiteQuote, summary="공용 QR 차량의 발리 당일 견적·10분 유효 토큰")
def quote(body: Quote, request: Request, session=DB):
    user = user_principal(request, session)
    require_schema(request.app.state.db)
    limited(request, user.uid_token)
    spot, item = resolve(request, session, body.qrCode.get_secret_value())
    from app.account_deletion_scope import new_work_allowed
    new_work_allowed(request.app.state.db, session, spot["spot_master_id"])
    _, price = plan(request, session, spot, item, body.returnDate)
    at = now().replace(tzinfo=timezone.utc)
    claims = {"sub": user.uid_token, "aud": "nadree-onsite-quote", "iat": int(at.timestamp()),
              "exp": int((at + timedelta(minutes=10)).timestamp()), "vehicleId": item["vehicle"]["vehicle_id"],
              "startDate": str(local_date(request, now())), "returnDate": str(body.returnDate),
              "totalPrice": price["totalFrom"], "currency": price["currency"]}
    return {"status": "success", "vehicleId": claims["vehicleId"], "spot": _spot_view(spot),
            "startDate": claims["startDate"], "returnDate": claims["returnDate"], "price": price,
            "quoteExpiresAt": (at + timedelta(minutes=10)).isoformat(),
            "quoteToken": jwt.encode(claims, quote_key(request), algorithm="HS256")}


def decode_quote(request, token, uid):
    try:
        claims = jwt.decode(token, quote_key(request), algorithms=["HS256"], audience="nadree-onsite-quote",
            options={"require": ["sub", "exp", "iat", "vehicleId", "startDate", "returnDate", "totalPrice", "currency"],
                     "verify_exp": False, "verify_iat": False})
        if claims["sub"] != uid or type(claims["exp"]) is not int or type(claims["iat"]) is not int:
            raise ValueError
        return claims
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise Problem(409, "ONSITE_QUOTE_INVALID") from None


def insert_reservation(request, session, spot, item, uid, return_date, *, key=None, evidence=None, approved=False):
    candidate, price = plan(request, session, spot, item, return_date)
    at, ident = now(), str(uuid.uuid4())
    candidate.update(reservation_id=ident, uid_token=uid, spot_master_id=spot["spot_master_id"],
        reservation_status="APPROVED" if approved else "REQUESTED", vehicle_assignment_status="PROVISIONAL" if approved else "SOFT_HOLD",
        assigned_vehicle_id=item["vehicle"]["vehicle_id"] if approved else None, client_request_id=key,
        hold_expires_at=day_end(request, local_date(request, at)), delivery_request_type="PICKUP",
        created_at=at, updated_at=at)
    candidate["required_criteria_json"].update(requestType="ONSITE", customerReceiptRequired=True,
        onsiteVehicleId=item["vehicle"]["vehicle_id"], onsiteRequest=evidence,
        paymentMethod=EXTERNAL, quote=price,
        selected={"spotMasterId": spot["spot_master_id"], "modelId": item["rental"]["model_id"],
                  "priceOptionId": price["pricingTiers"][0]["priceOptionId"]},
        pickupLocationSnapshot=location_snapshot(spot), returnLocationSnapshot=location_snapshot(spot))
    session.execute(request.app.state.db.table("MSP_RESERVATION").insert().values(**candidate))
    return candidate


def create_walkin(request, session, spot, item, uid, return_date, admin_id):
    require_schema(request.app.state.db)
    reservation = insert_reservation(request, session, spot, item, uid, return_date, approved=True)
    reservation_history(request, session, reservation, {}, "APPROVED", admin_id)
    return reservation


@router.post("/onsite/requests", response_model=CustomerOnsiteResult, responses={202: {"model": CustomerOnsiteResult}},
             summary="멱등 요청 키·영속 결과로 차량 고정 현장 신청")
def onsite_request(body: OnsiteRequest, request: Request, response: Response, session=REQUEST_DB):
    user = user_principal(request, session)
    require_schema(request.app.state.db)
    table = outcomes.require_schema(request.app.state.db)
    limited(request, user.uid_token)
    db = request.app.state.db
    key = body.clientRequestId
    if not outcomes.try_lock(session, user.uid_token, key):
        response.status_code, response.headers["Retry-After"] = 202, "2"
        return {"status": "success", **outcomes.outcome(key, "PROCESSING")}
    lock_key(session, "nadri-user", user.uid_token)
    user = user_principal(request, session)
    digest = outcomes.fingerprint(body)
    record = outcomes.find(session, table, user.uid_token, key)
    ident = outcomes.accepted_id(db, session, user.uid_token, key)
    if ident:
        if record and record["request_fingerprint"] != digest:
            raise Problem(409, "REQUEST_KEY_REUSED", request_outcome={
                **outcomes.outcome(key, "ACCEPTED"), "retrySameRequest": False})
        if not record:
            try:
                result = _submit_onsite(body, request, session, user.uid_token)
            except Problem as error:
                error.request_outcome = {**outcomes.outcome(key, "ACCEPTED"), "retrySameRequest": False}
                raise
            session.execute(table.insert().values(uid_token=user.uid_token, client_request_id=key,
                request_fingerprint=digest, request_state="ACCEPTED", reservation_id=ident,
                created_at=now(), updated_at=now()))
        else:
            result = nadree_reservation_detail(ident, request, session)
        return {**result, **outcomes.outcome(key, "ACCEPTED")}
    outcomes.start(session, table, user.uid_token, key, digest, record)
    try:
        result = _submit_onsite(body, request, session, user.uid_token)
    except Problem as error:
        outcomes.reject(session, table, user.uid_token, key, error)
    outcomes.accept(session, table, user.uid_token, key, result["item"]["reservationId"])
    return {**result, **outcomes.outcome(key, "ACCEPTED")}


def _submit_onsite(body, request, session, uid):
    db = request.app.state.db
    claims = decode_quote(request, body.quoteToken.get_secret_value(), uid)
    evidence = {key: claims[key] for key in ("vehicleId", "startDate", "returnDate", "totalPrice", "currency")}
    evidence["qrDigest"] = qr_digest(request, body.qrCode.get_secret_value())
    if str(body.returnDate) != claims["returnDate"]:
        raise Problem(409, "ONSITE_QUOTE_MISMATCH")
    r = db.table("MSP_RESERVATION")
    existing = session.execute(select(r).where(r.c.uid_token == uid,
        r.c.client_request_id == body.clientRequestId).with_for_update()).mappings().first()
    if existing:
        if (existing["required_criteria_json"] or {}).get("onsiteRequest") != evidence:
            raise Problem(409, "REQUEST_KEY_REUSED")
        return nadree_reservation_detail(existing["reservation_id"], request, session)
    stamp = int(now().replace(tzinfo=timezone.utc).timestamp())
    if not claims["iat"] <= stamp < claims["exp"] or claims["startDate"] != str(local_date(request, now())):
        raise Problem(409, "ONSITE_QUOTE_EXPIRED")
    spot, item = resolve(request, session, body.qrCode.get_secret_value())
    if item["vehicle"]["vehicle_id"] != claims["vehicleId"]:
        raise Problem(409, "ONSITE_QUOTE_MISMATCH")
    lock_key(session, "nadri-model", spot["spot_master_id"] + ":" + item["rental"]["model_id"])
    spot, item = resolve(request, session, body.qrCode.get_secret_value(), lock=True)
    from app.account_deletion_scope import new_work_allowed
    new_work_allowed(db, session, spot["spot_master_id"], lock=True)
    _, price = plan(request, session, spot, item, body.returnDate)
    if price["totalFrom"] != claims["totalPrice"] or price["currency"] != claims["currency"]:
        raise Problem(409, "ONSITE_QUOTE_CHANGED")
    reservation = insert_reservation(request, session, spot, item, uid, body.returnDate,
                                     key=body.clientRequestId, evidence=evidence)
    reservation_history(request, session, reservation, {}, "REQUESTED", uid, customer=True)
    queue_reservation_request(db, session, reservation["reservation_id"], spot["spot_master_id"])
    return nadree_reservation_detail(reservation["reservation_id"], request, session)


@router.get("/onsite/requests/{client_request_id}", response_model=CustomerOnsiteResult,
            responses={202: {"model": CustomerOnsiteResult}}, summary="본인 신청의 접수·확정 거절·처리 중·불명 결과 조회")
def request_result(client_request_id: RequestKey, request: Request, response: Response, session=DB):
    user = user_principal(request, session)
    require_schema(request.app.state.db)
    table = outcomes.require_schema(request.app.state.db)
    return _request_result(request, session, response, user.uid_token, client_request_id, table)


def _request_result(request, session, response, uid, key, table):
    ident = outcomes.accepted_id(request.app.state.db, session, uid, key)
    if ident:
        return {**nadree_reservation_detail(ident, request, session), **outcomes.outcome(key, "ACCEPTED")}
    record = outcomes.find(session, table, uid, key)
    if record and record["request_state"] == "REJECTED":
        return {"status": "success", **outcomes.outcome(key, "REJECTED", code=record["error_code"])}
    if outcomes.processing(session, uid, key):
        response.status_code, response.headers["Retry-After"] = 202, "2"
        return {"status": "success", **outcomes.outcome(key, "PROCESSING")}
    code = "ONSITE_REQUEST_OUTCOME_UNKNOWN" if record else "ONSITE_REQUEST_NOT_FOUND"
    raise Problem(503 if record else 404, code, request_outcome=outcomes.outcome(key, "UNKNOWN"))


@router.post("/onsite/requests/{client_request_id}/close", response_model=CustomerOnsiteResult,
             responses={202: {"model": CustomerOnsiteResult}}, summary="미접수 신청 키를 확정 종료해 늦은 생성 차단")
def close_request(client_request_id: RequestKey, request: Request, response: Response, session=REQUEST_DB):
    user = user_principal(request, session)
    limited(request, user.uid_token)
    require_schema(request.app.state.db)
    table = outcomes.require_schema(request.app.state.db)
    if not outcomes.try_lock(session, user.uid_token, client_request_id):
        response.status_code, response.headers["Retry-After"] = 202, "2"
        return {"status": "success", **outcomes.outcome(client_request_id, "PROCESSING")}
    ident = outcomes.accepted_id(request.app.state.db, session, user.uid_token, client_request_id)
    if ident:
        return {**nadree_reservation_detail(ident, request, session), **outcomes.outcome(client_request_id, "ACCEPTED")}
    record = outcomes.find(session, table, user.uid_token, client_request_id)
    if record and record["request_state"] == "ACCEPTED":
        raise Problem(503, "ONSITE_RESULT_UNAVAILABLE", request_outcome=outcomes.outcome(client_request_id, "UNKNOWN"))
    if not record or record["request_state"] != "REJECTED":
        outcomes.close(session, table, user.uid_token, client_request_id, record)
    return {"status": "success", **outcomes.outcome(client_request_id, "REJECTED",
        code=record["error_code"] if record and record["request_state"] == "REJECTED" else "ONSITE_REQUEST_CLOSED")}


@router.post("/reservations/{reservation_id}/receive", response_model=CustomerReservationDetail, summary="본인 예약·공용 QR 확인 후 명시적 인수 확정")
def receive(reservation_id: str, body: Qr, request: Request, session=DB):
    user = user_principal(request, session)
    limited(request, user.uid_token)
    db, r = request.app.state.db, request.app.state.db.table("MSP_RESERVATION")
    initial = session.execute(select(r).where(r.c.reservation_id == reservation_id, r.c.uid_token == user.uid_token)).mappings().first()
    if not initial:
        raise Problem(404, "RESERVATION_NOT_FOUND")
    require_schema(db)
    if initial["reservation_status"] in ("HANDED_OVER", "RETURNED") and initial.get("handed_over_at"):
        expected = (initial.get("required_criteria_json") or {}).get("receiptQrDigest", "")
        if not hmac.compare_digest(expected, qr_digest(request, body.qrCode.get_secret_value())):
            raise Problem(409, "RESERVATION_VEHICLE_MISMATCH")
        return nadree_reservation_detail(reservation_id, request, session)
    master = db.table("MSP_SPOT_MASTER")
    session.execute(select(master.c.spot_master_id).where(master.c.spot_master_id == initial["spot_master_id"]).with_for_update()).first()
    spot = _spot(request, session, initial["spot_master_id"])
    qr = verify_qr(request, session, spot, body.qrCode.get_secret_value(), lock=True)
    reservation = dict(session.execute(select(r).where(r.c.reservation_id == reservation_id).with_for_update()).mappings().one())
    if reservation["assigned_vehicle_id"] != qr["vehicle_id"]:
        raise Problem(409, "RESERVATION_VEHICLE_MISMATCH")
    if reservation["reservation_status"] in ("HANDED_OVER", "RETURNED") and reservation.get("handed_over_at"):
        return nadree_reservation_detail(reservation_id, request, session)
    if (reservation["reservation_status"] in (PENDING, "EXPIRED") and reservation.get("handed_over_at")
            and (not reservation.get("receipt_deadline_at") or now() >= reservation["receipt_deadline_at"])):
        raise Problem(409, "RECEIPT_DEADLINE_EXPIRED")
    if reservation["reservation_status"] != PENDING:
        raise Problem(409, "NOT_AWAITING_RECEIPT")
    paid_booking(request, session, reservation)
    vehicles = fleet(request, session, spot, model_id=reservation["model_id"], lock=True)
    item = vehicles.get(qr["vehicle_id"])
    if not item or item["state"]["status"] != "DISABLED" or item["state"]["status_reason"] != hold_reason(reservation_id):
        raise Problem(409, "RECEIPT_HOLD_INCONSISTENT")
    item["state"] = dict(item["state"], status="AVAILABLE", status_reason=None)
    contracts = contracts_for(request, session, list(vehicles))
    check_handover_vehicle(request, item, contracts, load_tiers(request, session, spot["spot_master_id"]))
    from app.rentals import require_no_contract
    require_no_contract(request, session, reservation)
    start_contract(request, session, spot, item, vehicles, contracts, user.uid_token,
        local_date(request, reservation["end_datetime"]), reservation=reservation)
    return nadree_reservation_detail(reservation_id, request, session)
