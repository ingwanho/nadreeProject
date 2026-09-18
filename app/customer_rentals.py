import secrets
import uuid
from datetime import date, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.availability import compute_assignment, reservation_history
from app.db import require_columns, transaction
from app.errors import Problem
from app.headers import refresh_header
from app.paypal import identifier
from app.pricing import daily_price, load_tiers
from app.rental_common import contracts_for, day_end, fleet, iso, local_date, lock_key, midnight
from app.rental_inputs import (NadriAvailability, NadriLogin, NadriPaymentCapture,
                               NadriPaymentOrder, NadriProfile, NadriRentalRequest, ReservationCancel)
from app.responses import Tokens
from app.security import fingerprint, now, sign_user_access, user_principal

router = APIRouter(prefix="/api/v1/nadri/rental", tags=["Nadri customer rentals"])
user_router = APIRouter(prefix="/api/v1/nadri/user", tags=["Nadri customer users"])
DB = Depends(transaction, scope="function")
USER_REFRESH_PREFIX = "nadri.rt."


def _db(request):
    return request.app.state.db


def _user_refresh_raw(request):
    raw = request.headers.get("X-Refresh-Token", "")
    if not raw.startswith(USER_REFRESH_PREFIX) or len(raw) > 256:
        raise Problem(401, "INVALID_REFRESH_TOKEN")
    return raw


def _user_refresh_row(request, session, raw=None, *, locked=False):
    raw = raw or _user_refresh_raw(request)
    table = _db(request).table("MSP_RENTAL_USER_REFRESH_TOKEN")
    query = select(table).where(table.c.token_hash == fingerprint(raw), table.c.revoked_at.is_(None),
                                table.c.expires_at > now())
    if locked:
        query = query.with_for_update()
    row = session.execute(query).mappings().first()
    if not row:
        raise Problem(401, "INVALID_REFRESH_TOKEN")
    return table, row


def _issue_user_refresh(request, session, uid_token, current):
    table = _db(request).table("MSP_RENTAL_USER_REFRESH_TOKEN")
    session.execute(update(table).where(table.c.uid_token == uid_token, table.c.revoked_at.is_(None),
                                        table.c.expires_at > current).values(revoked_at=current))
    raw = USER_REFRESH_PREFIX + secrets.token_urlsafe(48)
    token_id = str(uuid.uuid4())
    session.execute(table.insert().values(token_id=token_id, uid_token=uid_token, token_hash=fingerprint(raw),
                                          issued_at=current, expires_at=current + timedelta(days=request.app.state.settings.refresh_days)))
    return raw


def _local_period(request, start_date, return_date):
    return midnight(request, start_date), day_end(request, return_date) - timedelta(seconds=1)


def _days(start_date, return_date):
    return (return_date - start_date).days


def _active_spots(request, session):
    db = _db(request)
    master, contracts = db.table("MSP_SPOT_MASTER"), db.table("MSP_CONTRACT")
    result = []
    for row in session.execute(select(master).where(master.c.is_active == 1)).mappings():
        row = dict(row)
        contract = session.execute(select(contracts).where(contracts.c.contract_id == row["contract_id"])).mappings().first()
        today = local_date(request, now())
        if not contract or contract["status"] != "active":
            continue
        if (contract.get("start_date") and contract["start_date"] > today) or (contract.get("end_date") and contract["end_date"] < today):
            continue
        if (row.get("contract_start") and row["contract_start"] > today) or (row.get("contract_end") and row["contract_end"] < today):
            continue
        rent = session.execute(select(db.table("MSP_SPOT_RENT")).where(
            db.table("MSP_SPOT_RENT").c.spot_master_id == row["spot_master_id"])).mappings().first()
        row["rent"] = dict(rent) if rent else {}
        result.append(row)
    return result


def _spot(request, session, spot_id, *, active=True):
    db = _db(request)
    master = db.table("MSP_SPOT_MASTER")
    row = session.execute(select(master).where(master.c.spot_master_id == spot_id)).mappings().first()
    if not row:
        raise Problem(404, "SPOT_NOT_FOUND")
    row = dict(row)
    if active and row.get("is_active") != 1:
        raise Problem(409, "SPOT_UNAVAILABLE")
    contract = session.execute(select(db.table("MSP_CONTRACT")).where(
        db.table("MSP_CONTRACT").c.contract_id == row["contract_id"])).mappings().first()
    today = local_date(request, now())
    if active and (not contract or contract["status"] != "active" or
                   (contract.get("start_date") and contract["start_date"] > today) or
                   (contract.get("end_date") and contract["end_date"] < today) or
                   (row.get("contract_start") and row["contract_start"] > today) or
                   (row.get("contract_end") and row["contract_end"] < today)):
        raise Problem(409, "SPOT_UNAVAILABLE")
    rent = db.table("MSP_SPOT_RENT")
    rent_row = session.execute(select(rent).where(rent.c.spot_master_id == spot_id)).mappings().first()
    row["rent"] = dict(rent_row) if rent_row else {}
    return row


def _model(request, session, model_id):
    table = _db(request).table("MSP_VEHICLE_MODEL")
    row = session.execute(select(table).where(table.c.model_id == model_id, table.c.is_active == 1)).mappings().first()
    if not row:
        raise Problem(404, "MODEL_NOT_FOUND")
    return dict(row)


def _spot_view(spot):
    return {"spotMasterId": spot["spot_master_id"], "unitCode": spot.get("unit_code"),
            "spotName": spot.get("spot_name"), "phone": spot.get("phone"),
            "location": {"address": spot.get("address"), "zipCode": spot.get("zip_code"),
                         "latitude": float(spot["lat"]) if spot.get("lat") is not None else None,
                         "longitude": float(spot["lng"]) if spot.get("lng") is not None else None}}


def _model_view(model):
    return {"modelId": model["model_id"], "brand": model.get("brand"), "modelName": model.get("model_name"),
            "cc": model.get("cc"), "vehicleType": model.get("vehicle_type"),
            "modelImageKey": model.get("model_image_key")}


def _delivery(request, session, spot, model, pickup, returned, *, required=False):
    if not required:
        return {"deliveryRegionId": None, "deliveryStartFee": 0, "deliveryReturnFee": 0,
                "deliveryTotalFee": 0, "deliveryRequestType": "PICKUP"}
    service = (spot.get("rent") or {}).get("delivery_service_type") or "NONE"
    if service != "START_AND_RETURN" or model.get("is_delivery_supported") != 1:
        raise Problem(409, "DELIVERY_NOT_SUPPORTED")
    db = _db(request)
    link, region = db.table("MSP_SPOT_DELIVERY_REGION"), db.table("MSP_DELIVERY_REGION")
    configured = session.execute(select(link, region).join(region, region.c.delivery_region_id == link.c.delivery_region_id).where(
        link.c.spot_master_id == spot["spot_master_id"], link.c.is_delivery_enabled == 1,
        region.c.is_active == 1)).mappings().all()
    if not configured:
        raise Problem(409, "DELIVERY_NOT_SUPPORTED")

    def matches(address, row):
        raw = (address or "").casefold()
        return any(token and token.casefold() in raw for token in (row.get("region_name"), row.get("region_code")))

    pick = [row for row in configured if matches(pickup, row)]
    ret = [row for row in configured if matches(returned, row)]
    common = [row for row in configured if (not pick or row in pick) and (not ret or row in ret)]
    if pick and ret:
        common = [row for row in pick if row in ret]
    if len(common) != 1:
        if len(configured) == 1:
            common = configured
        else:
            raise Problem(409, "DELIVERY_REGION_NOT_SUPPORTED")
    row = dict(common[0])
    return {"deliveryRegionId": row["delivery_region_id"],
            "deliveryStartFee": int(row.get("start_delivery_fee") or 0),
            "deliveryReturnFee": int(row.get("return_delivery_fee") or 0),
            "deliveryTotalFee": int(row.get("start_delivery_fee") or 0) + int(row.get("return_delivery_fee") or 0),
            "deliveryRequestType": "START_AND_RETURN"}


def _price_groups(request, session, spot, model_id, start, end, *, check_availability=True):
    vehicles = fleet(request, session, spot, model_id=model_id)
    if not vehicles:
        return []
    start_day, end_day = local_date(request, start), local_date(request, end)
    dates = [start_day + timedelta(days=index) for index in range((end_day - start_day).days)]
    inventory_rows = []
    if check_availability:
        try:
            inventory = _db(request).table("MSP_MODEL_DAILY_INVENTORY")
            inventory_rows = session.execute(select(inventory).where(inventory.c.spot_master_id == spot["spot_master_id"],
                inventory.c.model_id == model_id, inventory.c.target_date.in_(dates))).mappings().all()
        except (SQLAlchemyError, Problem):
            inventory_rows = []
        if inventory_rows and (len(inventory_rows) < len(dates) or any((row.get("available_qty") or 0) < 1 for row in inventory_rows)):
            return []
    tiers = load_tiers(request, session, spot["spot_master_id"])
    prices = {}
    for item in vehicles.values():
        price = daily_price(item, tiers)
        if price is None:
            continue
        kind = item["rental"]["price_type"]
        prices[(kind, int(price))] = True
    if not check_availability:
        return [(kind, price) for kind, price in sorted(prices)]
    contracts = contracts_for(request, session, list(vehicles))
    groups = []
    for kind, price in sorted(prices):
        candidate = {"reservation_id": "QUOTE-" + uuid.uuid4().hex[:28],
                     "start_datetime": start, "end_datetime": end, "model_id": model_id,
                     "assigned_vehicle_id": None, "vehicle_assignment_status": "SOFT_HOLD",
                     "required_criteria_json": {"priceType": kind, "dailyPrice": price}}
        try:
            compute_assignment(request, session, spot, vehicles, contracts, candidate=candidate)
        except Problem as error:
            if error.code == "VEHICLE_UNAVAILABLE":
                continue
            raise
        groups.append((kind, price))
    return groups


def _price_view(request, groups, start_date, return_date, delivery, requested_total=None, model=None):
    days = _days(start_date, return_date)
    currency = request.app.state.settings.rental_currency
    totals = [price * days + delivery["deliveryTotalFee"] for _, price in groups]
    daily = [price for _, price in groups]
    tiers = []
    configured = []
    if model is not None:
        try:
            configured = load_tiers(request, request._nadri_session, request._nadri_spot["spot_master_id"])
        except AttributeError:
            configured = []
    for kind, price in groups:
        if kind == "PREMIUM":
            tier = {"priceType": kind, "tierType": None, "minCc": None, "maxCc": None,
                    "dailyPriceFrom": price, "dailyPriceTo": price}
        else:
            matches = [row for row in configured if model is not None and model.get("cc") is not None
                       and row["min_cc"] <= model["cc"] <= row["max_cc"]]
            specific = [row for row in matches if row["tier_type"] == "BASIC"]
            chosen = specific or [row for row in matches if row["tier_type"] == "BASE"]
            row = chosen[0] if chosen else None
            tier = {"priceType": kind, "tierType": row["tier_type"] if row else "BASIC",
                    "minCc": row["min_cc"] if row else None, "maxCc": row["max_cc"] if row else None,
                    "dailyPriceFrom": price, "dailyPriceTo": price}
        tiers.append(tier)
    return {"currency": currency, "rentalDays": days, "dailyFrom": min(daily), "dailyTo": max(daily),
            "dailyPriceFrom": min(daily), "dailyPriceTo": max(daily),
            "rentalFrom": min(daily) * days, "rentalTo": max(daily) * days,
            "pricingTiers": tiers, "deliveryStart": delivery["deliveryStartFee"],
            "deliveryReturn": delivery["deliveryReturnFee"], "deliveryTotal": delivery["deliveryTotalFee"],
            "deliveryStartFee": delivery["deliveryStartFee"], "deliveryReturnFee": delivery["deliveryReturnFee"],
            "deliveryTotalFee": delivery["deliveryTotalFee"], "totalFrom": min(totals), "totalTo": max(totals),
            "requestedTotal": requested_total}


def _availability_for(request, session, body, *, selected_spot=None, selected_model=None, check_availability=True):
    start, end = _local_period(request, body.startDate, body.returnDate)
    spots = [_spot(request, session, selected_spot)] if selected_spot else _active_spots(request, session)
    models = [_model(request, session, selected_model)] if selected_model else None
    items = []
    for spot in spots:
        candidate_models = models or [dict(row) for row in session.execute(select(_db(request).table("MSP_VEHICLE_MODEL")).where(
            _db(request).table("MSP_VEHICLE_MODEL").c.is_active == 1,
            _db(request).table("MSP_VEHICLE_MODEL").c.cc == body.cc if hasattr(body, "cc") else _db(request).table("MSP_VEHICLE_MODEL").c.model_id == selected_model)).mappings()]
        for model in candidate_models:
            if selected_model and model["model_id"] != selected_model:
                continue
            try:
                delivery = _delivery(request, session, spot, model, getattr(body, "pickupLocation", None),
                                     getattr(body, "returnLocation", None), required=body.deliveryRequested)
            except Problem as error:
                if selected_spot or error.code not in ("DELIVERY_NOT_SUPPORTED", "DELIVERY_REGION_NOT_SUPPORTED"):
                    raise
                continue
            request._nadri_session, request._nadri_spot = session, spot
            groups = _price_groups(request, session, spot, model["model_id"], start, end,
                                   check_availability=check_availability)
            if not groups:
                continue
            price = _price_view(request, groups, body.startDate, body.returnDate, delivery,
                                getattr(body, "totalPrice", None), model=model)
            items.append({"spot": _spot_view(spot), "model": _model_view(model), "price": price,
                          "delivery": {**delivery, "pickupLocation": getattr(body, "pickupLocation", None),
                                       "returnLocation": getattr(body, "returnLocation", None)}})
    return items


def _quote_for_request(request, session, body):
    if body.currency != request.app.state.settings.rental_currency:
        raise Problem(409, "CURRENCY_NOT_SUPPORTED")
    items = _availability_for(request, session, body, selected_spot=body.spotMasterId,
                              selected_model=body.modelId)
    if not items:
        raise Problem(409, "RENTAL_UNAVAILABLE")
    item = items[0]
    price = item["price"]
    if not price["totalFrom"] <= body.totalPrice <= price["totalTo"]:
        raise Problem(409, "PRICE_QUOTE_MISMATCH")
    return item


def _number(value):
    if value is None:
        return None
    value = Decimal(value)
    return int(value) if value == value.to_integral_value() else float(value)


def _payment_view(payment):
    if not payment:
        return None
    return {"paymentId": payment["payment_id"], "paymentProvider": payment.get("payment_provider"),
            "paymentStatus": payment.get("payment_status"), "paymentEnvironment": payment.get("payment_environment"),
            "paypalOrderId": payment.get("paypal_order_id"), "paypalCaptureId": payment.get("paypal_capture_id"),
            "totalPrice": _number(payment.get("total_price")), "currency": payment.get("currency"),
            "refundedAmount": _number(payment.get("refunded_amount")), "refundStatus": payment.get("refund_status", "NONE"),
            "paypalRefundId": payment.get("paypal_refund_id"), "paidAt": payment.get("paid_at").isoformat() if payment.get("paid_at") else None}


def _latest_payment(request, session, reservation_id=None, contract_id=None):
    table = _db(request).table("MSP_RENTAL_PAYMENT")
    cond = []
    if reservation_id:
        cond.append(table.c.reservation_id == reservation_id)
    if contract_id:
        cond.append(table.c.rental_contract_id == contract_id)
    if not cond:
        return None
    return session.execute(select(table).where(or_(*cond), table.c.payment_environment == request.app.state.settings.paypal_environment)
                           .order_by(table.c.payment_id.desc())).mappings().first()


def _record_view(request, reservation, contract, payment, spot, model):
    if not spot:
        return None
    criteria = (reservation or {}).get("required_criteria_json") or {}
    quote = criteria.get("quote") if isinstance(criteria, dict) else None
    if not isinstance(quote, dict):
        quote = {}
    start_value = (contract or {}).get("actual_start_time") or (reservation or {}).get("start_datetime")
    end_value = (contract or {}).get("actual_end_time") or (reservation or {}).get("end_datetime")
    return_date = (contract or {}).get("planned_end_date") or (local_date(request, end_value) if end_value else None)
    status = (contract or {}).get("contract_status")
    reservation_status = (reservation or {}).get("reservation_status")
    pstatus = payment.get("payment_status") if payment else None
    if contract:
        availability = pstatus or "PAYMENT_NOT_REQUIRED"
    elif reservation_status == "REQUESTED":
        availability = "WAITING_APPROVAL"
    elif pstatus in ("CREATED", "PENDING"):
        availability = pstatus
    elif pstatus in ("PAID", "PARTIALLY_REFUNDED", "REFUNDED"):
        availability = "PAID"
    else:
        availability = "PAYMENT_REQUIRED" if reservation_status == "APPROVED" else pstatus
    delivery_type = (reservation or {}).get("delivery_request_type", "PICKUP")
    return {"recordType": "RENTAL" if contract else "RESERVATION",
            "reservationId": (reservation or {}).get("reservation_id"),
            "rentalContractId": (contract or {}).get("rental_contract_id"),
            "bookedNo": ("BO" + reservation["reservation_id"]) if reservation else ("RT" + contract["rental_contract_id"]),
            "reservationStatus": reservation_status, "rentalStatus": status,
            "vehicleAssignmentStatus": (reservation or {}).get("vehicle_assignment_status"),
            "paymentAvailability": availability, "spot": _spot_view(spot), "model": _model_view(model) if model else None,
            "startDate": local_date(request, start_value).isoformat() if start_value else None,
            "returnDate": return_date.isoformat() if isinstance(return_date, date) else None,
            "actualStartTime": iso(request, (contract or {}).get("actual_start_time")),
            "actualEndTime": iso(request, (contract or {}).get("actual_end_time")),
            "deliveryRequestType": delivery_type,
            "pickupLocation": (reservation or {}).get("delivery_start_address"),
            "returnLocation": (reservation or {}).get("delivery_return_address"),
            "delivery": {"deliveryRequestType": delivery_type,
                         "pickupLocation": (reservation or {}).get("delivery_start_address"),
                         "returnLocation": (reservation or {}).get("delivery_return_address"),
                         "deliveryTotalFee": int((reservation or {}).get("delivery_total_fee_snapshot") or 0)},
            "price": {"currency": quote.get("currency") or (payment or {}).get("currency") or request.app.state.settings.rental_currency,
                      "totalFrom": _number(quote.get("totalFrom", quote.get("calculatedTotalFrom", (payment or {}).get("total_price")))),
                      "totalTo": _number(quote.get("totalTo", quote.get("calculatedTotalTo", (payment or {}).get("total_price"))))},
            "payment": _payment_view(payment)}


def _customer_records(request, session, uid, *, completed=False, page=1, size=20):
    db = _db(request)
    rt, ct = db.table("MSP_RESERVATION"), db.table("MSP_RENTAL_CONTRACT")
    reservations = [dict(row) for row in session.execute(select(rt).where(rt.c.uid_token == uid)).mappings()]
    contracts = [dict(row) for row in session.execute(select(ct).where(ct.c.uid_token == uid)).mappings()]
    if completed:
        contracts = [c for c in contracts if c["contract_status"] == "RETURNED" and c["actual_end_time"] is not None]
        linked_ids = {c.get("reservation_id") for c in contracts if c.get("reservation_id")}
        reservations = [dict(row) for row in session.execute(select(rt).where(rt.c.reservation_id.in_(linked_ids), rt.c.uid_token == uid)).mappings()] if linked_ids else []
    else:
        reservations = [r for r in reservations if r["reservation_status"] in ("REQUESTED", "APPROVED", "HANDED_OVER")]
        contracts = [c for c in contracts if c["contract_status"] in ("ON_RENT", "OVERDUE") and c["actual_end_time"] is None]
    reservation_by_id = {r["reservation_id"]: r for r in reservations}
    vehicle_ids = {c["vehicle_id"] for c in contracts}
    vehicle_models = {}
    if vehicle_ids:
        rv, models = db.table("MSP_RENTAL_VEHICLE"), db.table("MSP_VEHICLE_MODEL")
        for row in session.execute(select(rv.c.vehicle_id, models).join(models, models.c.model_id == rv.c.model_id).where(rv.c.vehicle_id.in_(vehicle_ids))).mappings():
            vehicle_models[row["vehicle_id"]] = dict(row)
    spot_ids = {r["spot_master_id"] for r in reservations} | {c["pickup_spot_master_id"] for c in contracts}
    spots = {}
    if spot_ids:
        master = db.table("MSP_SPOT_MASTER")
        spots = {row["spot_master_id"]: dict(row) for row in session.execute(select(master).where(master.c.spot_master_id.in_(spot_ids))).mappings()}
    model_ids = {r["model_id"] for r in reservations}
    models = {}
    if model_ids:
        mt = db.table("MSP_VEHICLE_MODEL")
        models = {row["model_id"]: dict(row) for row in session.execute(select(mt).where(mt.c.model_id.in_(model_ids))).mappings()}
    records = []
    linked = set()
    for contract in contracts:
        reservation = reservation_by_id.get(contract.get("reservation_id"))
        if reservation:
            linked.add(reservation["reservation_id"])
        model = models.get(reservation["model_id"]) if reservation else vehicle_models.get(contract["vehicle_id"])
        payment = _latest_payment(request, session, reservation_id=contract.get("reservation_id"), contract_id=contract["rental_contract_id"])
        spot_id = reservation["spot_master_id"] if reservation else contract["pickup_spot_master_id"]
        records.append(_record_view(request, reservation, contract, payment, spots.get(spot_id), model))
    if not completed:
        for reservation in reservations:
            if reservation["reservation_id"] in linked:
                continue
            payment = _latest_payment(request, session, reservation_id=reservation["reservation_id"])
            records.append(_record_view(request, reservation, None, payment, spots.get(reservation["spot_master_id"]), models.get(reservation["model_id"])))
    if completed:
        records.sort(key=lambda item: (item.get("actualEndTime") or "", item.get("rentalContractId") or ""), reverse=True)
    else:
        records.sort(key=lambda item: (item.get("actualStartTime") or item.get("startDate") or "", item.get("reservationId") or ""))
    total = len(records)
    start = (page - 1) * size
    return records[start:start + size], total


def _user_view(request, session, user):
    items, _ = _customer_records(request, session, user["uid_token"], page=1, size=100)
    return {"uidToken": user["uid_token"], "name": user.get("name"), "age": user.get("age"),
            "gender": user.get("gender"), "nationality": user.get("nationality"), "ongoingRequests": items}


@user_router.post("/login")
def nadri_login(body: NadriLogin, request: Request, session: Session = DB):
    db = _db(request)
    table = db.table("MSP_RENTAL_USER")
    lock_key(session, "nadri-user", body.UID)
    row = session.execute(select(table).where(table.c.uid_token == body.UID).with_for_update()).mappings().first()
    is_new = row is None
    if row is None:
        try:
            with session.begin_nested():
                session.execute(table.insert().values(uid_token=body.UID, created_at=now(), updated_at=now()))
        except IntegrityError:
            pass
        row = session.execute(select(table).where(table.c.uid_token == body.UID).with_for_update()).mappings().first()
    if row is None:
        raise Problem(503, "RENTAL_USER_STORAGE_UNAVAILABLE")
    user = dict(row)
    current = now()
    if body.fcmToken is not None:
        values = {"fcm_token": body.fcmToken, "fcm_token_updated_at": current, "updated_at": current}
        require_columns(table, values)
        session.execute(update(table).where(table.c.uid_token == body.UID).values(**values))
        user.update(values)
    refresh_token = _issue_user_refresh(request, session, body.UID, current)
    auth_time = None
    if user.get("user_access_revoked_at") is not None:
        auth_time = int(user["user_access_revoked_at"].replace(tzinfo=timezone.utc).timestamp()) + 1
    return {"status": "success", "isNewUser": is_new,
            "refreshToken": refresh_token,
            "accessToken": sign_user_access(request.app.state.settings, body.UID, auth_time=auth_time),
            "user": _user_view(request, session, user)}


@user_router.post("/refresh", response_model=Tokens, dependencies=[Depends(refresh_header)])
@user_router.get("/refresh", response_model=Tokens, dependencies=[Depends(refresh_header)])
def nadri_refresh(request: Request, session: Session = DB):
    raw = _user_refresh_raw(request)
    _, initial = _user_refresh_row(request, session, raw, locked=False)
    lock_key(session, "nadri-user", initial["uid_token"])
    users = _db(request).table("MSP_RENTAL_USER")
    user = session.execute(select(users).where(users.c.uid_token == initial["uid_token"]).with_for_update()).mappings().first()
    if not user:
        raise Problem(401, "INVALID_REFRESH_TOKEN")
    revoked = user.get("user_access_revoked_at")
    if revoked is not None and initial["issued_at"] <= revoked:
        raise Problem(401, "INVALID_REFRESH_TOKEN")
    table, row = _user_refresh_row(request, session, raw, locked=True)
    new_raw = USER_REFRESH_PREFIX + secrets.token_urlsafe(48)
    result = session.execute(update(table).where(table.c.token_id == row["token_id"],
                                                 table.c.token_hash == row["token_hash"],
                                                 table.c.revoked_at.is_(None)).values(token_hash=fingerprint(new_raw)))
    if result.rowcount != 1:
        raise Problem(401, "INVALID_REFRESH_TOKEN")
    issued = int(row["issued_at"].replace(tzinfo=timezone.utc).timestamp())
    if revoked is not None:
        issued = max(issued, int(revoked.replace(tzinfo=timezone.utc).timestamp()) + 1)
    return {"status": "success", "accessToken": sign_user_access(request.app.state.settings,
                                                                     row["uid_token"], auth_time=issued),
            "refreshToken": new_raw}


@user_router.patch("/profile")
def nadri_profile(body: NadriProfile, request: Request, session: Session = DB):
    user = user_principal(request, session)
    fields = body.model_fields_set
    if not fields or any(getattr(body, field) is None for field in fields):
        raise Problem(422, "EMPTY_PROFILE_UPDATE")
    table = _db(request).table("MSP_RENTAL_USER")
    values = {}
    for source, target in (("NAME", "name"), ("Age", "age"), ("GENDER", "gender"), ("NATIONALITY", "nationality")):
        if source in fields:
            values[target] = getattr(body, source)
    if "fcmToken" in fields:
        values.update(fcm_token=body.fcmToken, fcm_token_updated_at=now())
    values["updated_at"] = now()
    require_columns(table, values)
    session.execute(update(table).where(table.c.uid_token == user.uid_token).values(**values))
    row = session.execute(select(table).where(table.c.uid_token == user.uid_token)).mappings().one()
    return {"status": "success", "user": {"uidToken": row["uid_token"], "name": row.get("name"), "age": row.get("age"),
                                             "gender": row.get("gender"), "nationality": row.get("nationality")}}


@user_router.post("/logout", dependencies=[Depends(refresh_header)])
@user_router.get("/logout", dependencies=[Depends(refresh_header)])
def nadri_logout(request: Request, session: Session = DB):
    user = user_principal(request, session)
    raw = request.headers.get("X-Refresh-Token")
    refresh_table = _db(request).table("MSP_RENTAL_USER_REFRESH_TOKEN")
    if raw is not None:
        raw = _user_refresh_raw(request)
        refresh_table, refresh_row = _user_refresh_row(request, session, raw, locked=False)
        if refresh_row["uid_token"] != user.uid_token:
            raise Problem(401, "TOKEN_PAIR_MISMATCH")
    lock_key(session, "nadri-user", user.uid_token)
    table = _db(request).table("MSP_RENTAL_USER")
    fresh = session.execute(select(table).where(table.c.uid_token == user.uid_token).with_for_update()).mappings().first()
    if not fresh:
        raise Problem(401, "INVALID_NADRI_USER_TOKEN")
    if raw is not None:
        _, refresh_row = _user_refresh_row(request, session, raw, locked=True)
        if refresh_row["uid_token"] != user.uid_token:
            raise Problem(401, "TOKEN_PAIR_MISMATCH")
    if "user_access_revoked_at" not in table.c:
        raise Problem(503, "RENTAL_USER_SCHEMA_UPDATE_REQUIRED")
    revoked_at = now()
    session.execute(update(table).where(table.c.uid_token == user.uid_token).values(user_access_revoked_at=revoked_at, updated_at=revoked_at))
    session.execute(update(refresh_table).where(refresh_table.c.uid_token == user.uid_token,
                                                refresh_table.c.revoked_at.is_(None)).values(revoked_at=revoked_at))
    return {"status": "success"}


@router.post("/availability")
def nadri_availability(body: NadriAvailability, request: Request, session: Session = DB):
    items = _availability_for(request, session, body)
    return {"status": "success", "items": [{"spot": item["spot"], "model": item["model"], "price": item["price"]} for item in items]}


@router.post("/request")
def nadri_request(body: NadriRentalRequest, request: Request, session: Session = DB):
    user = user_principal(request, session)
    item = _quote_for_request(request, session, body)
    start, end = _local_period(request, body.startDate, body.returnDate)
    db = _db(request)
    key = ":".join((user.uid_token, body.spotMasterId, body.modelId, body.startDate.isoformat(), body.returnDate.isoformat(), str(body.deliveryRequested)))
    lock_key(session, "nadri-request", key)
    table = db.table("MSP_RESERVATION")
    recent = session.execute(select(table.c.reservation_id).where(
        table.c.uid_token == user.uid_token, table.c.spot_master_id == body.spotMasterId, table.c.model_id == body.modelId,
        table.c.start_datetime == start, table.c.end_datetime == end, table.c.reservation_status.in_(("REQUESTED", "APPROVED")),
        table.c.created_at >= now() - timedelta(seconds=60))).first()
    if recent:
        raise Problem(409, "DUPLICATE_RENTAL_REQUEST")
    delivery = item["delivery"]
    reservation_id = str(uuid.uuid4())
    at = now()
    quote = dict(item["price"])
    quote["requestedTotal"] = body.totalPrice
    availability_request = {"startDate": body.startDate.isoformat(), "returnDate": body.returnDate.isoformat(),
                            "cc": item["model"].get("cc"), "deliveryRequested": body.deliveryRequested,
                            "pickupLocation": body.pickupLocation, "returnLocation": body.returnLocation}
    quote["calculatedTotalFrom"] = quote["totalFrom"]
    quote["calculatedTotalTo"] = quote["totalTo"]
    criteria = {"source": "nadri.rental.availability", "availabilityRequest": availability_request,
                "selected": {"spotMasterId": body.spotMasterId, "modelId": body.modelId}, "quote": quote,
                "priceType": item["price"]["pricingTiers"][0]["priceType"], "dailyPrice": item["price"]["dailyFrom"]}
    values = dict(reservation_id=reservation_id, uid_token=user.uid_token, spot_master_id=body.spotMasterId, model_id=body.modelId,
                  assigned_vehicle_id=None, vehicle_assignment_status="SOFT_HOLD", required_criteria_json=criteria,
                  start_datetime=start, end_datetime=end, delivery_region_id=delivery["deliveryRegionId"],
                  delivery_request_type=delivery["deliveryRequestType"], delivery_start_address=body.pickupLocation,
                  delivery_return_address=body.returnLocation, start_delivery_fee_snapshot=delivery["deliveryStartFee"],
                  return_delivery_fee_snapshot=delivery["deliveryReturnFee"], delivery_total_fee_snapshot=delivery["deliveryTotalFee"],
                  reservation_status="REQUESTED", hold_expires_at=None,
                  created_at=at, updated_at=at)
    session.execute(table.insert().values(**values))
    reservation = dict(values)
    reservation_history(request, session, reservation, values, "REQUESTED", user.uid_token)
    return {"status": "success", "reservationId": reservation_id, "bookedNo": "BO" + reservation_id,
            "reservationStatus": "REQUESTED", "vehicleAssignmentStatus": "SOFT_HOLD", "paymentAvailability": "WAITING_APPROVAL",
            "paymentStatus": "WAITING_APPROVAL",
            "spotMasterId": body.spotMasterId, "modelId": body.modelId, "totalPrice": body.totalPrice,
            "currency": body.currency, "deliveryRequestType": delivery["deliveryRequestType"],
            "spot": item["spot"], "model": item["model"], "price": quote}


def _reservation_for_payment(request, session, user, reservation_id):
    table = _db(request).table("MSP_RESERVATION")
    row = session.execute(select(table).where(table.c.reservation_id == reservation_id, table.c.uid_token == user.uid_token).with_for_update()).mappings().first()
    if not row:
        raise Problem(404, "RESERVATION_NOT_FOUND")
    if row["reservation_status"] != "APPROVED":
        raise Problem(409, "RESERVATION_NOT_APPROVED_FOR_PAYMENT")
    return dict(row)


def _revalidate_reservation_quote(request, session, reservation):
    criteria = reservation.get("required_criteria_json") or {}
    source = criteria.get("availabilityRequest") if isinstance(criteria, dict) else None
    stored = criteria.get("quote") if isinstance(criteria, dict) else None
    if not isinstance(source, dict) or not isinstance(stored, dict):
        raise Problem(409, "PAYMENT_QUOTE_CHANGED")
    spot = _spot(request, session, reservation["spot_master_id"])
    model = _model(request, session, reservation["model_id"])
    start_date = date.fromisoformat(source["startDate"])
    return_date = date.fromisoformat(source["returnDate"])
    start, end = _local_period(request, start_date, return_date)
    delivery = _delivery(request, session, spot, model, source.get("pickupLocation"), source.get("returnLocation"),
                         required=bool(source.get("deliveryRequested")))
    groups = _price_groups(request, session, spot, model["model_id"], start, end, check_availability=False)
    if not groups:
        raise Problem(409, "PAYMENT_QUOTE_CHANGED")
    request._nadri_session, request._nadri_spot = session, spot
    current = _price_view(request, groups, start_date, return_date, delivery, model=model)
    if (stored.get("currency") != current["currency"] or stored.get("totalFrom", stored.get("calculatedTotalFrom")) != current["totalFrom"]
            or stored.get("totalTo", stored.get("calculatedTotalTo")) != current["totalTo"]):
        raise Problem(409, "PAYMENT_QUOTE_CHANGED")
    return stored


def _payment_result(payment, approval_url=None):
    view = _payment_view(payment)
    return {"status": "success", "paymentId": payment["payment_id"], "reservationId": payment.get("reservation_id"),
            "paymentStatus": payment["payment_status"], "paypalOrderId": payment.get("paypal_order_id"),
            "paypalCaptureId": payment.get("paypal_capture_id"), "approvalUrl": approval_url,
            "totalPrice": _number(payment.get("total_price")), "serverTotalPrice": _number(payment.get("total_price")),
            "currency": payment["currency"], "payment": view}


@router.post("/payment/order")
def nadri_payment_order(body: NadriPaymentOrder, request: Request, session: Session = DB):
    user = user_principal(request, session)
    reservation = _reservation_for_payment(request, session, user, body.reservationId)
    db = _db(request)
    table = db.table("MSP_RENTAL_PAYMENT")
    existing = session.execute(select(table).where(table.c.reservation_id == reservation["reservation_id"],
        table.c.payment_environment == request.app.state.settings.paypal_environment).order_by(table.c.payment_id.desc()).with_for_update()).mappings().first()
    if existing:
        if existing["payment_status"] in ("PAID", "PARTIALLY_REFUNDED", "REFUNDED"):
            raise Problem(409, "PAYMENT_ALREADY_PAID")
        if existing["payment_status"] in ("CREATED", "PENDING") and existing.get("paypal_order_id"):
            approval = None
            try:
                approval = request.app.state.paypal.approval_url(request.app.state.paypal.get("orders", existing["paypal_order_id"]))
            except (Problem, AttributeError, SQLAlchemyError):
                approval = None
            return _payment_result(dict(existing), approval)
    quote = _revalidate_reservation_quote(request, session, reservation)
    if quote.get("requestedTotal") is None:
        raise Problem(409, "PAYMENT_QUOTE_UNAVAILABLE")
    total = Decimal(str(quote["requestedTotal"]))
    if total <= 0:
        raise Problem(409, "PAYMENT_QUOTE_UNAVAILABLE")
    payment_values = dict(reservation_id=reservation["reservation_id"], rental_contract_id=None, payment_provider="PAYPAL",
        payment_environment=request.app.state.settings.paypal_environment, payment_status="CREATED", paypal_order_id=None,
        paypal_capture_id=None, total_price=total, currency=quote.get("currency", request.app.state.settings.rental_currency),
        refunded_amount=Decimal("0"), refund_status="NONE", created_at=now(), updated_at=now())
    session.execute(table.insert().values(**payment_values))
    session.flush()
    payment = session.execute(select(table).where(table.c.reservation_id == reservation["reservation_id"],
        table.c.paypal_order_id.is_(None)).order_by(table.c.payment_id.desc()).with_for_update()).mappings().first()
    if not payment:
        raise Problem(503, "PAYPAL_SERVICE_UNAVAILABLE")
    try:
        result = request.app.state.paypal.create_order("nadree-order-" + str(payment["payment_id"]), payment["currency"], total, reservation["reservation_id"])
        order_id = identifier(result.get("id")) if isinstance(result, dict) and result.get("id") else None
        if not order_id:
            raise Problem(503, "PAYPAL_SERVICE_UNAVAILABLE")
    except Problem:
        session.execute(update(table).where(table.c.payment_id == payment["payment_id"]).values(payment_status="FAILED", updated_at=now()))
        raise
    try:
        approval = request.app.state.paypal.approval_url(result)
    except (Problem, AttributeError):
        session.execute(update(table).where(table.c.payment_id == payment["payment_id"]).values(
            paypal_order_id=order_id, payment_status="FAILED", updated_at=now()))
        raise Problem(503, "PAYPAL_APPROVAL_URL_MISSING")
    session.execute(update(table).where(table.c.payment_id == payment["payment_id"]).values(paypal_order_id=order_id, updated_at=now()))
    payment = dict(payment, paypal_order_id=order_id)
    return _payment_result(payment, approval)


@router.post("/payment/capture")
def nadri_payment_capture(body: NadriPaymentCapture, request: Request, session: Session = DB):
    user = user_principal(request, session)
    db = _db(request)
    table = db.table("MSP_RENTAL_PAYMENT")
    payment = session.execute(select(table).where(table.c.payment_id == body.paymentId).with_for_update()).mappings().first()
    if not payment:
        raise Problem(404, "PAYMENT_NOT_FOUND")
    reservation = _reservation_for_payment(request, session, user, payment["reservation_id"]) if payment.get("reservation_id") else None
    if not reservation and payment.get("rental_contract_id"):
        contract = _db(request).table("MSP_RENTAL_CONTRACT")
        if not session.execute(select(contract.c.rental_contract_id).where(
                contract.c.rental_contract_id == payment["rental_contract_id"], contract.c.uid_token == user.uid_token)).first():
            raise Problem(404, "PAYMENT_NOT_FOUND")
        raise Problem(409, "PAYMENT_STATE_INVALID")
    if not reservation:
        raise Problem(404, "PAYMENT_NOT_FOUND")
    if payment["payment_status"] in ("PAID", "PARTIALLY_REFUNDED", "REFUNDED"):
        return _payment_result(dict(payment))
    if payment["payment_status"] == "PENDING" and payment.get("paypal_capture_id"):
        return _payment_result(dict(payment))
    if payment["payment_status"] not in ("CREATED", "PENDING") or not payment.get("paypal_order_id"):
        raise Problem(409, "PAYMENT_STATE_INVALID")
    try:
        result = request.app.state.paypal.capture_order(payment["paypal_order_id"], "nadree-capture-" + str(payment["payment_id"]))
    except Problem:
        session.execute(update(table).where(table.c.payment_id == payment["payment_id"]).values(payment_status="FAILED", updated_at=now()))
        raise
    capture_id = request.app.state.paypal.capture_reference_from_order(result)
    capture_status = result.get("status") if isinstance(result, dict) else None
    status = "FAILED" if capture_status in ("DECLINED", "DENIED") else "PENDING"
    values = dict(payment_status=status, updated_at=now())
    if capture_id:
        values["paypal_capture_id"] = capture_id
    session.execute(update(table).where(table.c.payment_id == payment["payment_id"]).values(**values))
    payment = dict(payment)
    payment.update(values)
    return _payment_result(payment)


@router.get("/ongoing")
def nadri_ongoing(request: Request, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100), session: Session = DB):
    user = user_principal(request, session)
    items, total = _customer_records(request, session, user.uid_token, page=page, size=pageSize)
    return {"status": "success", "items": items, "page": page, "pageSize": pageSize, "totalCount": total,
            "hasNext": page * pageSize < total}


@router.get("/completed")
def nadri_completed(request: Request, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100), session: Session = DB):
    user = user_principal(request, session)
    items, total = _customer_records(request, session, user.uid_token, completed=True, page=page, size=pageSize)
    return {"status": "success", "items": items, "page": page, "pageSize": pageSize, "totalCount": total,
            "hasNext": page * pageSize < total}


@router.post("/request/cancel")
def cancel_request(body: ReservationCancel, request: Request, session: Session = DB):
    user = user_principal(request, session)
    db = request.app.state.db
    reservation_table = db.table("MSP_RESERVATION")
    reservation = session.execute(select(reservation_table).where(
        reservation_table.c.reservation_id == body.reservationId,
        reservation_table.c.uid_token == user.uid_token).with_for_update()).mappings().first()
    if not reservation:
        raise Problem(404, "RESERVATION_NOT_FOUND")
    if reservation["reservation_status"] not in ("REQUESTED", "APPROVED"):
        raise Problem(409, "RESERVATION_STATE_INVALID")
    contract_table = db.table("MSP_RENTAL_CONTRACT")
    if session.execute(select(contract_table.c.rental_contract_id).where(
            contract_table.c.reservation_id == reservation["reservation_id"])).first():
        raise Problem(409, "RESERVATION_ALREADY_HANDED_OVER")

    payment_table = db.table("MSP_RENTAL_PAYMENT")
    payments = session.execute(select(payment_table).where(
        payment_table.c.reservation_id == reservation["reservation_id"],
        payment_table.c.payment_environment == request.app.state.settings.paypal_environment)
        .order_by(payment_table.c.payment_id.desc()).with_for_update()).mappings().all()
    refund_status = "NOT_REQUIRED"
    for payment in payments:
        if payment["paid_at"] is not None or payment["payment_status"] in ("PAID", "PARTIALLY_REFUNDED", "REFUNDED"):
            raise Problem(409, "PAYMENT_REFUND_ADMIN_ONLY")
        if payment["payment_status"] == "PENDING":
            raise Problem(409, "PAYMENT_IN_PROGRESS")
        if payment["payment_status"] in ("CREATED", "PENDING"):
            session.execute(update(payment_table).where(payment_table.c.payment_id == payment["payment_id"]).values(
                payment_status="CANCELED", refund_status="NOT_REQUIRED", refund_reason=body.reason, updated_at=now()))

    at = now()
    values = dict(reservation_status="CANCELED", vehicle_assignment_status="RELEASED",
                  assigned_vehicle_id=None, vehicle_assigned_at=None, updated_at=at)
    session.execute(update(reservation_table).where(
        reservation_table.c.reservation_id == reservation["reservation_id"],
        reservation_table.c.reservation_status.in_(("REQUESTED", "APPROVED"))).values(**values))
    reservation_history(request, session, reservation, values, "CANCELLED", user.uid_token, body.reason)
    return {"status": "success", "reservationId": reservation["reservation_id"],
            "bookedNo": "BO" + reservation["reservation_id"], "reservationStatus": "CANCELED",
            "refundStatus": refund_status}
