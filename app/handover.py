"""Reservation-backed, customer-first handover with independent completion states."""
import json
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import NoSuchTableError

from app.db import transaction
from app.errors import Problem
from app.fcm import _manager_recipients, _queue
from app.handover_inputs import (ClaimHandover, EmptyCommand, FormPatch, PrepareMedia,
                                 RespondHandover, ReviewHandover, StartHandover)
from app.handover_media import MIME_EXTENSIONS, PHOTO_LIMIT
from app.headers import bearer
from app.rental_common import context, iso, local_date
from app.rental_profile import NUMBER_FIELDS, decrypt, read_sns, sync_personal
from app.responses import (AccommodationHistory, HandoverList, HandoverMediaResult,
                           HandoverResult, HandoverUploadResult)
from app.security import encrypted_phone, now, user_principal
from app.spot_hierarchy import unit_name

router = APIRouter(tags=["Rental handover"], dependencies=[bearer])
DB = Depends(transaction, scope="function")
SLOTS = {"VEHICLE_VIDEO": ("vehicleVideo", "video_key"), "PASSPORT_PHOTO": ("passportPhoto", "passport_photo_key"),
         "DRIVER_LICENSE_PHOTO": ("driverLicensePhoto", "driver_license_photo_key"), "EXTRA_PHOTO": ("extraPhoto", "extra_photo_key")}
FORM_COLUMNS = {**NUMBER_FIELDS, "accommodationLocation": "accommodation_location_enc", "helmetCount": "helmet_count"}
CLOSED = ("STARTED", "CANCELED")


def is_v2(reservation):
    return ((reservation or {}).get("required_criteria_json") or {}).get("handoverFlowVersion") == 2


def table(request):
    return request.app.state.db.table("MSP_RENTAL_HANDOVER")


def require_schema(db):
    from app.rental_schema import metadata
    checks = {"MSP_RENTAL_HANDOVER": set(metadata.tables["MSP_RENTAL_HANDOVER"].c.keys()),
        "MSP_RENTAL_USER": {"passport_number_enc", "driver_license_number_enc", "sns_info"},
        "MSP_RENTAL_CONTRACT": {"handover_id"}, "MSP_VEHICLE_STATUS": {"untracked_rent_until"}}
    try:
        if any(not fields.issubset(db.table(name).c.keys()) for name, fields in checks.items()):
            raise Problem(503, "HANDOVER_SCHEMA_UPDATE_REQUIRED")
    except NoSuchTableError:
        raise Problem(503, "HANDOVER_SCHEMA_UPDATE_REQUIRED") from None


def current(request, session, reservation_id, *, include_canceled=True):
    h = table(request)
    query = select(h).where(h.c.reservation_id == reservation_id)
    row = session.execute(query.where(h.c.handover_status != "CANCELED")).mappings().first()
    if row is None and include_canceled:
        r = reservation_row(request, session, reservation_id)
        last_id = (r.get("required_criteria_json") or {}).get("handoverId")
        if last_id:
            row = session.execute(query.where(h.c.handover_id == last_id)).mappings().first()
        else:
            row = session.execute(query.order_by(h.c.created_at.desc(), h.c.handover_id.desc())).mappings().first()
    return dict(row) if row else None


def save(request, session, row, **values):
    values["updated_at"] = now()
    session.execute(update(table(request)).where(table(request).c.handover_id == row["handover_id"]).values(**values))
    row.update(values)
    return row


def prepare(request, session, reservation, price):
    existing = current(request, session, reservation["reservation_id"], include_canceled=False)
    if existing:
        if existing["final_price"] != price:
            raise Problem(409, "FINAL_PRICE_ALREADY_CONFIRMED")
        return existing
    at = now()
    values = dict(handover_id=str(uuid.uuid4()), reservation_id=reservation["reservation_id"],
        uid_token=reservation["uid_token"], spot_master_id=reservation["spot_master_id"],
        vehicle_id=reservation["assigned_vehicle_id"], assigned_admin_id=None, final_price=price,
        customer_status="NOT_STARTED", admin_status="UNASSIGNED", handover_status="NOT_STARTED",
        signature_status="NOT_STARTED", start_date=local_date(request, reservation["start_datetime"]),
        return_date=local_date(request, reservation["end_datetime"]), media_state_json={}, created_at=at, updated_at=at)
    session.execute(table(request).insert().values(**values))
    r = request.app.state.db.table("MSP_RESERVATION")
    criteria = dict(reservation.get("required_criteria_json") or {}, handoverId=values["handover_id"])
    session.execute(update(r).where(r.c.reservation_id == reservation["reservation_id"]).values(required_criteria_json=criteria))
    return values


def close_for_reservation(request, session, reservation, reason="RESERVATION_CLOSED"):
    if not is_v2(reservation):
        return
    h = current(request, session, reservation["reservation_id"], include_canceled=False)
    if h and h["handover_status"] not in CLOSED:
        save(request, session, h, handover_status="CANCELED", canceled_at=now(), cancel_reason=reason)


def expire_for_reservation(db, session, reservation, at):
    if is_v2(reservation):
        h = db.table("MSP_RENTAL_HANDOVER")
        session.execute(update(h).where(h.c.reservation_id == reservation["reservation_id"],
            h.c.handover_status.not_in(CLOSED)).values(handover_status="CANCELED", canceled_at=at,
                                                     cancel_reason="RESERVATION_EXPIRED", updated_at=at))


def reservation_row(request, session, ident, *, lock=False):
    r = request.app.state.db.table("MSP_RESERVATION")
    query = select(r).where(r.c.reservation_id == ident)
    row = session.execute(query.with_for_update() if lock else query).mappings().first()
    if not row:
        raise Problem(404, "RESERVATION_NOT_FOUND")
    return dict(row)


def _load(request, session, ident, *, admin=False, write=False):
    h = table(request)
    initial = session.execute(select(h).where(h.c.handover_id == ident)).mappings().first()
    if not initial:
        raise Problem(404, "HANDOVER_REQUIRED")
    if admin:
        actor, spot = context(request, session, write=write, settlement=True)
        if spot["spot_master_id"] != initial["spot_master_id"]:
            raise Problem(404, "HANDOVER_REQUIRED")
        actor_id = actor.admin["admin_id"]
    else:
        actor_id = user_principal(request, session).uid_token
        if initial["uid_token"] != actor_id:
            raise Problem(404, "HANDOVER_REQUIRED")
        if write:
            master = request.app.state.db.table("MSP_SPOT_MASTER")
            session.execute(select(master.c.spot_master_id).where(
                master.c.spot_master_id == initial["spot_master_id"]).with_for_update()).first()
    reservation_row(request, session, initial["reservation_id"], lock=write)
    query = select(h).where(h.c.handover_id == ident)
    row = session.execute(query.with_for_update() if write else query).mappings().one()
    if write and row["handover_status"] not in CLOSED:
        r = reservation_row(request, session, row["reservation_id"])
        if r["reservation_status"] != "APPROVED":
            raise Problem(409, "HANDOVER_CLOSED")
    return dict(row), actor_id


def _open(row):
    if row["handover_status"] in CLOSED or row["handover_status"] == "NOT_STARTED":
        raise Problem(409, "HANDOVER_CLOSED")


def assignee(row, admin_id):
    if row.get("assigned_admin_id") != admin_id:
        raise Problem(403, "HANDOVER_ASSIGNEE_REQUIRED")


def pending(request, row):
    value = row.get("pending_changes_enc")
    return json.loads(decrypt(request.app.state.settings, value)) if value else None


def media_summary(row):
    states = row.get("media_state_json") or {}
    return {slot: {"required": kind in ("VEHICLE_VIDEO", "EXTRA_PHOTO"), **{k: value[k] for k in (
        "status", "contentType", "sizeBytes", "durationSeconds") if k in value}}
        for kind, (slot, _) in SLOTS.items()
        for value in [states.get(kind, {"status": "NOT_UPLOADED"})]}


def photos_ready(row):
    states = row.get("media_state_json") or {}
    return (states.get("EXTRA_PHOTO") or {}).get("status") == "READY" and all(value.get("status") in ("READY", "SKIPPED", "NOT_UPLOADED") for kind, value in states.items()
               if kind != "VEHICLE_VIDEO")


def blocked(row):
    if row["handover_status"] in CLOSED:
        return ["HANDOVER_CLOSED"]
    reasons = []
    if not row.get("submitted_at"):
        reasons.append("CUSTOMER_FORM_NOT_SUBMITTED")
    if row["admin_status"] != "CONFIRMED":
        reasons.append("ADMIN_REVIEW_NOT_COMPLETED")
    if ((row.get("media_state_json") or {}).get("VEHICLE_VIDEO") or {}).get("status") != "READY":
        reasons.append("VIDEO_NOT_READY")
    if row["signature_status"] != "COMPLETED":
        reasons.append("SIGNATURE_NOT_COMPLETED")
    if row["customer_status"] == "CHANGE_PENDING":
        reasons.append("HANDOVER_CHANGE_PENDING")
    if not photos_ready(row):
        reasons.append("MEDIA_NOT_READY")
    return reasons


def recalculate(request, session, row):
    if row["handover_status"] in CLOSED or row["handover_status"] == "NOT_STARTED":
        return row
    target = "WAITING_CUSTOMER" if row["customer_status"] == "CHANGE_PENDING" else "IN_PROGRESS" if blocked(row) else "READY"
    if row["handover_status"] != target:
        save(request, session, row, handover_status=target)
    return row


def summary(row, *, admin_id=None):
    reasons = blocked(row)
    return {"customerStatus": row["customer_status"], "adminStatus": row["admin_status"],
        "signatureStatus": row["signature_status"], "handoverStatus": row["handover_status"],
        "assignedAdminId": row.get("assigned_admin_id"),
        "canReviewForm": bool(admin_id and admin_id == row.get("assigned_admin_id") and row.get("submitted_at")
            and row["admin_status"] == "REVIEWING" and row["handover_status"] not in CLOSED and photos_ready(row)),
        "canStartRental": bool(admin_id and admin_id == row.get("assigned_admin_id") and not reasons),
        "startBlockedReasons": reasons}


def eligibility(request, session, row, *, admin_id=None):
    result = summary(row, admin_id=admin_id)
    if result["canStartRental"]:
        from app.rentals import booking_handover_status
        master = request.app.state.db.table("MSP_SPOT_MASTER")
        root = session.execute(select(master).where(master.c.spot_master_id == row["spot_master_id"])).mappings().one()
        status = booking_handover_status(request, session, root, reservation_row(request, session, row["reservation_id"]))
        if not status["canHandOver"]:
            result.update(canStartRental=False, startBlockedReasons=[status["handoverBlockedReason"]])
    return result


def form_view(request, session, row):
    db = request.app.state.db
    users, master, vehicles, extras, models = (db.table(name) for name in (
        "MSP_RENTAL_USER", "MSP_SPOT_MASTER", "MSP_VEHICLE", "MSP_RENTAL_VEHICLE", "MSP_VEHICLE_MODEL"))
    user = session.execute(select(users).where(users.c.uid_token == row["uid_token"])).mappings().first() or {}
    spot = session.execute(select(master).where(master.c.spot_master_id == row["spot_master_id"])).mappings().first() or {}
    vehicle = session.execute(select(vehicles).where(vehicles.c.vehicle_id == row["vehicle_id"])).mappings().first()
    extra = session.execute(select(extras).where(extras.c.vehicle_id == row["vehicle_id"])).mappings().first()
    model_id = extra["model_id"] if extra else row.get("model_id")
    model = session.execute(select(models).where(models.c.model_id == model_id)).mappings().first() if model_id else None
    result = {key: decrypt(request.app.state.settings, row.get(column)) if key != "helmetCount" else row.get(column)
              for key, column in FORM_COLUMNS.items()}
    if row.get("handover_status") == "NOT_STARTED":
        for key, column in NUMBER_FIELDS.items():
            result[key] = decrypt(request.app.state.settings, user.get(column))
    return {"spotName": unit_name(spot), "customerName": user.get("name"),
        "vehicleNo": (extra or {}).get("plate_number_full") or (vehicle or {}).get("plate_number"),
        "modelName": (model or {}).get("model_name"), **result,
        "startDate": row["start_date"].isoformat(), "returnDate": row["return_date"].isoformat(),
        "snsInfo": read_sns(user.get("sns_info"))}


def resource(request, session, row, *, admin_id=None):
    r = reservation_row(request, session, row["reservation_id"])
    ct = request.app.state.db.table("MSP_RENTAL_CONTRACT")
    cid = session.scalar(select(ct.c.rental_contract_id).where(ct.c.handover_id == row["handover_id"]))
    changes = pending(request, row)
    return {"handoverId": row["handover_id"], "reservationId": row["reservation_id"],
        "rentalContractId": cid, "spotMasterId": row["spot_master_id"], "vehicleId": row["vehicle_id"],
        "finalPrice": row["final_price"], "currency": ((r.get("required_criteria_json") or {}).get("quote") or {}).get("currency"),
        **eligibility(request, session, row, admin_id=admin_id), "form": form_view(request, session, row)
            if not admin_id or row.get("submitted_at") else None,
        "pendingChange": changes if changes and changes.get("decision") is None else None,
        "restartHandoverId": changes.get("restartHandoverId") if changes else None,
        "media": media_summary(row)}


def detail_fields(request, session, reservation, contract, *, detailed=False, admin_id=None):
    """Both detail surfaces use the same form; lists contain no personal form."""
    row = None
    if contract and contract.get("handover_id"):
        row = session.execute(select(table(request)).where(table(request).c.handover_id == contract["handover_id"])).mappings().first()
    elif is_v2(reservation):
        row = current(request, session, reservation["reservation_id"])
    criteria = (reservation or {}).get("required_criteria_json") or {}
    currency = (criteria.get("quote") or {}).get("currency")
    vehicle_id = (contract or {}).get("vehicle_id") or (reservation or {}).get("assigned_vehicle_id") or criteria.get("onsiteVehicleId")
    values = {"handoverId": row["handover_id"] if row else None, "finalPrice": row["final_price"] if row else None,
        "currency": currency, "handover": eligibility(request, session, row, admin_id=admin_id) if row else None,
        "vehicleId": vehicle_id, "form": None, "media": media_summary(row) if row and detailed else None}
    if detailed:
        if row:
            if not admin_id or row.get("submitted_at"):
                values["form"] = form_view(request, session, row)
        else:
            uid = (reservation or {}).get("uid_token") or (contract or {}).get("uid_token")
            if uid:
                source = dict(uid_token=uid, vehicle_id=vehicle_id,
                    spot_master_id=(reservation or {}).get("spot_master_id") or (contract or {}).get("pickup_spot_master_id"),
                    model_id=(reservation or {}).get("model_id"),
                    start_date=local_date(request, (reservation or {}).get("start_datetime") or contract["actual_start_time"]),
                    return_date=local_date(request, reservation["end_datetime"]) if reservation else contract["planned_end_date"])
                # Past contracts never acquire today's profile document numbers.
                if not contract and not admin_id:
                    users = request.app.state.db.table("MSP_RENTAL_USER")
                    profile = session.execute(select(users).where(users.c.uid_token == uid)).mappings().first() or {}
                    source.update(passport_number_enc=profile.get("passport_number_enc"),
                                  driver_license_number_enc=profile.get("driver_license_number_enc"))
                if not admin_id or not is_v2(reservation):
                    values["form"] = form_view(request, session, source)
    return values


def start_rental(request, session, actor, root, reservation, body):
    """The only writer which starts a v2 contract; always revalidate resources."""
    from app.rental_common import action_result, contracts_for, expire_maintenance, fleet, verify_qr
    from app.rentals import (check_handover_reservation, check_handover_vehicle, customer,
                             paid_booking, start_contract)
    from app.pricing import load_tiers
    if not body.handoverId:
        raise Problem(409, "HANDOVER_REQUIRED")
    h, actor_id = _load(request, session, body.handoverId, admin=True, write=True)
    if h["reservation_id"] != reservation["reservation_id"]:
        raise Problem(409, "RESERVATION_VEHICLE_MISMATCH")
    assignee(h, actor_id)
    qr = verify_qr(request, session, root, body.qrCode.get_secret_value(), lock=True)
    if qr["vehicle_id"] != h["vehicle_id"] or reservation["assigned_vehicle_id"] != h["vehicle_id"]:
        raise Problem(409, "RESERVATION_VEHICLE_MISMATCH")
    ct = request.app.state.db.table("MSP_RENTAL_CONTRACT")
    existing = session.execute(select(ct).where(ct.c.reservation_id == h["reservation_id"])).mappings().first()
    if existing:
        if existing.get("handover_id") != h["handover_id"]:
            raise Problem(409, "RESERVATION_ALREADY_HANDED_OVER")
        return action_result(request, actor, existing["contract_status"], {
            "bookedNo": "BO" + reservation["reservation_id"], "rentalContractId": existing["rental_contract_id"],
            "handoverId": h["handover_id"], "handoverStatus": h["handover_status"],
            "contractStatus": existing["contract_status"], "finalPrice": h["final_price"],
            "currency": ((reservation.get("required_criteria_json") or {}).get("quote") or {}).get("currency")})
    _open(h)
    if blocked(h) or h["handover_status"] != "READY":
        raise Problem(409, "HANDOVER_NOT_READY")
    vehicles = fleet(request, session, root, model_id=reservation["model_id"], lock=True)
    item = vehicles.get(h["vehicle_id"])
    if item is None:
        raise Problem(404, "VEHICLE_NOT_FOUND")
    contracts = contracts_for(request, session, list(vehicles))
    expire_maintenance(request, session, vehicles, contracts)
    tiers = load_tiers(request, session, root["spot_master_id"])
    check_handover_vehicle(request, item, contracts, tiers)
    check_handover_reservation(request, reservation, item, vehicles, tiers)
    customer(request, session, h["uid_token"])
    paid_booking(request, session, reservation)
    data = start_contract(request, session, root, item, vehicles, contracts, h["uid_token"], h["return_date"],
        reservation=reservation, handover_id=h["handover_id"], actor_id=actor_id)
    save(request, session, h, handover_status="STARTED", started_at=now())
    data.update(handoverId=h["handover_id"], handoverStatus="STARTED", finalPrice=h["final_price"],
                currency=((reservation.get("required_criteria_json") or {}).get("quote") or {}).get("currency"))
    return action_result(request, actor, "ON_RENT", data)


def notify(request, session, row, event, *, customer=False, all_admins=False):
    db = request.app.state.db
    data = {"type": event, "reservationId": row["reservation_id"], "handoverId": row["handover_id"],
            "handoverStatus": row["handover_status"]}
    if customer:
        users = db.table("MSP_RENTAL_USER")
        user = session.execute(select(users).where(users.c.uid_token == row["uid_token"])).mappings().first()
        recipients = [{"id": user["uid_token"], "token": user.get("fcm_token"), "updated_at": user.get("fcm_token_updated_at")}] if user else []
        owner_table, owner_key = "MSP_RENTAL_USER", "uid_token"
    else:
        recipients = _manager_recipients(db, session, row["spot_master_id"])
        if not all_admins:
            recipients = [r for r in recipients if r["id"] == row.get("assigned_admin_id")]
        owner_table, owner_key = "MSP_ADMIN", "admin_id"
    _queue(session, table=owner_table, key_column=owner_key, recipients=recipients, event=event,
           title="Rental handover update", body="The rental handover has been updated. Open the app to continue.", data=data)
    if not customer:
        from app.notifications import record_notification
        record_notification(db, session, row["spot_master_id"], event, "HANDOVER", row["handover_id"],
                            "handover:" + row["handover_id"] + ":" + event)


@router.post("/api/v1/nadree/rental/reservations/{reservation_id}/handover", response_model=HandoverResult)
def start(reservation_id: str, body: StartHandover, request: Request, session=DB):
    user = user_principal(request, session)
    initial = reservation_row(request, session, reservation_id)
    if initial["uid_token"] != user.uid_token:
        raise Problem(404, "RESERVATION_NOT_FOUND")
    master = request.app.state.db.table("MSP_SPOT_MASTER")
    session.execute(select(master.c.spot_master_id).where(master.c.spot_master_id == initial["spot_master_id"]).with_for_update()).first()
    r = reservation_row(request, session, reservation_id, lock=True)
    if r["reservation_status"] != "APPROVED":
        raise Problem(409, "RESERVATION_NOT_APPROVED")
    h = current(request, session, reservation_id, include_canceled=False)
    if not h:
        raise Problem(409, "HANDOVER_REQUIRED")
    h, _ = _load(request, session, h["handover_id"], write=True)
    prior = session.scalar(select(table(request).c.handover_id).where(table(request).c.uid_token == user.uid_token,
        table(request).c.client_request_id == body.clientRequestId))
    if prior and prior != h["handover_id"]:
        raise Problem(409, "REQUEST_KEY_REUSED")
    if h.get("client_request_id"):
        if h["client_request_id"] != body.clientRequestId:
            raise Problem(409, "HANDOVER_ALREADY_ACTIVE")
    else:
        users = request.app.state.db.table("MSP_RENTAL_USER")
        profile = session.execute(select(users).where(users.c.uid_token == user.uid_token)).mappings().one()
        save(request, session, h, client_request_id=body.clientRequestId, customer_started_at=now(),
             customer_status="DRAFT", handover_status="IN_PROGRESS", passport_number_enc=profile.get("passport_number_enc"),
             driver_license_number_enc=profile.get("driver_license_number_enc"))
        notify(request, session, h, "HANDOVER_STARTED", all_admins=True)
    return {"status": "success", "item": resource(request, session, h)}


@router.get("/api/v1/nadree/rental/handovers/{handover_id}", response_model=HandoverResult)
def customer_detail(handover_id: str, request: Request, session=DB):
    h, _ = _load(request, session, handover_id)
    return {"status": "success", "item": resource(request, session, h)}


@router.get("/nadreego/handovers", response_model=HandoverList)
def admin_list(request: Request, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
               handoverStatus: str | None = Query(None, max_length=20), session=DB):
    actor, root = context(request, session)
    h = table(request)
    where = h.c.spot_master_id == root["spot_master_id"]
    if handoverStatus:
        where &= h.c.handover_status == handoverStatus
    count = session.scalar(select(func.count()).select_from(h).where(where))
    records = session.execute(select(h).where(where).order_by(h.c.created_at.desc(), h.c.handover_id)
        .offset((page - 1) * pageSize).limit(pageSize)).mappings()
    return {"status": "success", "items": [{"handoverId": r["handover_id"], "reservationId": r["reservation_id"],
        "vehicleId": r["vehicle_id"], **eligibility(request, session, r, admin_id=actor.admin["admin_id"])} for r in records],
        "page": page, "pageSize": pageSize, "totalCount": count, "hasNext": page * pageSize < count}


@router.get("/nadreego/handovers/{handover_id}", response_model=HandoverResult)
def admin_detail(handover_id: str, request: Request, session=DB):
    h, actor = _load(request, session, handover_id, admin=True)
    return {"status": "success", "item": resource(request, session, h, admin_id=actor)}


@router.patch("/api/v1/nadree/rental/handovers/{handover_id}/form", response_model=HandoverResult)
def update_form(handover_id: str, body: FormPatch, request: Request, session=DB):
    h, _ = _load(request, session, handover_id, write=True)
    _open(h)
    if h["customer_status"] != "DRAFT":
        raise Problem(409, "HANDOVER_CLOSED")
    fields = body.model_dump(exclude_unset=True)
    values = {FORM_COLUMNS[key]: value if key == "helmetCount" else encrypted_phone(request.app.state.settings, value)
              for key, value in fields.items() if key in FORM_COLUMNS}
    sync_personal(request, session, h["uid_token"], fields)
    save(request, session, h, **values)
    return {"status": "success", "item": resource(request, session, h)}


@router.post("/api/v1/nadree/rental/handovers/{handover_id}/submit", response_model=HandoverResult)
def submit_form(handover_id: str, body: EmptyCommand, request: Request, session=DB):
    h, _ = _load(request, session, handover_id, write=True)
    _open(h)
    if h.get("submitted_at") is None:
        if not h.get("passport_number_enc") or not h.get("accommodation_location_enc") or h.get("helmet_count") is None:
            raise Problem(422, "INVALID_INPUT")
        save(request, session, h, customer_status="SUBMITTED", submitted_at=now())
        notify(request, session, h, "HANDOVER_FORM_SUBMITTED")
    return {"status": "success", "item": resource(request, session, h)}


@router.post("/api/v1/nadree/rental/handovers/{handover_id}/signature/complete", response_model=HandoverResult)
def complete_signature(handover_id: str, body: EmptyCommand, request: Request, session=DB):
    h, _ = _load(request, session, handover_id, write=True)
    _open(h)
    if h["signature_status"] != "COMPLETED":
        if not h.get("submitted_at"):
            raise Problem(409, "CUSTOMER_FORM_NOT_SUBMITTED")
        if h["customer_status"] == "CHANGE_PENDING":
            raise Problem(409, "HANDOVER_CHANGE_PENDING")
        if ((h.get("media_state_json") or {}).get("VEHICLE_VIDEO") or {}).get("status") != "READY":
            raise Problem(409, "VIDEO_NOT_READY")
        save(request, session, h, signature_status="COMPLETED", customer_status="CONFIRMED")
        recalculate(request, session, h)
        notify(request, session, h, "HANDOVER_CUSTOMER_COMPLETED")
    return {"status": "success", "item": resource(request, session, h)}


@router.post("/nadreego/handovers/{handover_id}/claim", response_model=HandoverResult)
def claim(handover_id: str, body: ClaimHandover, request: Request, session=DB):
    h, actor = _load(request, session, handover_id, admin=True, write=True)
    _open(h)
    if h.get("assigned_admin_id"):
        if h["assigned_admin_id"] != actor:
            raise Problem(409, "HANDOVER_ALREADY_ASSIGNED")
    else:
        save(request, session, h, assigned_admin_id=actor, admin_status="REVIEWING")
    return {"status": "success", "item": resource(request, session, h, admin_id=actor)}


@router.post("/nadreego/handovers/{handover_id}/review", response_model=HandoverResult)
def review(handover_id: str, body: ReviewHandover, request: Request, session=DB):
    h, actor = _load(request, session, handover_id, admin=True, write=True)
    _open(h)
    assignee(h, actor)
    if not h.get("submitted_at"):
        raise Problem(409, "CUSTOMER_FORM_NOT_SUBMITTED")
    states = dict(h.get("media_state_json") or {})
    for kind in body.skipPhotoKinds:
        if (states.get(kind) or {}).get("status") != "READY":
            states[kind] = {"status": "SKIPPED"}
    save(request, session, h, media_state_json=states)
    if not photos_ready(h):
        raise Problem(409, "MEDIA_NOT_READY")
    prior = pending(request, h)
    if body.action == "CONFIRM":
        if prior and prior.get("decision") is None:
            raise Problem(409, "HANDOVER_CHANGE_PENDING")
        if h["admin_status"] != "CONFIRMED":
            save(request, session, h, admin_status="CONFIRMED", admin_confirmed_at=now())
    else:
        fields = body.changes.model_dump(exclude_unset=True)
        if prior:
            if prior["changes"] == fields and prior["reason"] == body.reason:
                return {"status": "success", "item": resource(request, session, h, admin_id=actor)}
            raise Problem(409, "HANDOVER_CHANGE_PENDING" if prior.get("decision") is None else "HANDOVER_CHANGE_STALE")
        if h["admin_status"] == "CONFIRMED":
            raise Problem(409, "HANDOVER_CHANGE_STALE")
        before = form_view(request, session, h)
        value = {"changes": fields, "before": {key: before[key] for key in fields}, "reason": body.reason, "decision": None}
        save(request, session, h, pending_changes_enc=encrypted_phone(request.app.state.settings, json.dumps(value)),
             customer_status="CHANGE_PENDING", admin_status="CHANGES_PROPOSED", handover_status="WAITING_CUSTOMER")
        notify(request, session, h, "HANDOVER_CHANGES_PROPOSED", customer=True)
    recalculate(request, session, h)
    return {"status": "success", "item": resource(request, session, h, admin_id=actor)}


@router.post("/api/v1/nadree/rental/handovers/{handover_id}/changes/respond", response_model=HandoverResult)
def respond(handover_id: str, body: RespondHandover, request: Request, session=DB):
    h, _ = _load(request, session, handover_id, write=True)
    value = pending(request, h)
    if value and value.get("decision"):
        if value["decision"] != body.decision:
            raise Problem(409, "HANDOVER_CHANGE_STALE")
        return {"status": "success", "item": resource(request, session, h)}
    _open(h)
    if not value or h["customer_status"] != "CHANGE_PENDING":
        raise Problem(409, "HANDOVER_CHANGE_STALE")
    value["decision"] = body.decision
    if body.decision == "ACCEPT":
        fields = value["changes"]
        updates = {FORM_COLUMNS[key]: val if key == "helmetCount" else encrypted_phone(request.app.state.settings, val)
                   for key, val in fields.items() if key in FORM_COLUMNS}
        sync_personal(request, session, h["uid_token"], fields)
        save(request, session, h, **updates, pending_changes_enc=encrypted_phone(request.app.state.settings, json.dumps(value)),
             admin_status="CONFIRMED", admin_confirmed_at=now(),
             customer_status="CONFIRMED" if h["signature_status"] == "COMPLETED" else "SUBMITTED")
        recalculate(request, session, h)
    else:
        save(request, session, h, customer_status="REJECTED", handover_status="CANCELED",
             canceled_at=now(), cancel_reason="HANDOVER_CHANGE_REJECTED")
        replacement = prepare(request, session, reservation_row(request, session, h["reservation_id"]), h["final_price"])
        value["restartHandoverId"] = replacement["handover_id"]
        save(request, session, h, pending_changes_enc=encrypted_phone(request.app.state.settings, json.dumps(value)))
    notify(request, session, h, "HANDOVER_CHANGES_ACCEPTED" if body.decision == "ACCEPT" else "HANDOVER_CHANGES_REJECTED")
    return {"status": "success", "item": resource(request, session, h)}


def _media_actor(request, session, ident, *, write=False):
    admin = request.url.path.startswith("/nadreego/")
    h, actor = _load(request, session, ident, admin=admin, write=write)
    return h, actor, admin


def _media_write(h, actor, admin, kind):
    _open(h)
    if (kind == "VEHICLE_VIDEO") == admin:
        raise Problem(403, "PERMISSION_DENIED")
    if admin:
        assignee(h, actor)
        if h["admin_status"] == "CONFIRMED":
            raise Problem(409, "HANDOVER_CLOSED")
    else:
        if not h.get("submitted_at"):
            raise Problem(409, "CUSTOMER_FORM_NOT_SUBMITTED")
        if h["signature_status"] == "COMPLETED":
            raise Problem(409, "HANDOVER_CLOSED")


@router.post("/api/v1/nadree/rental/handovers/{handover_id}/media/uploads", response_model=HandoverUploadResult)
@router.post("/nadreego/handovers/{handover_id}/media/uploads", response_model=HandoverUploadResult)
def prepare_media(handover_id: str, body: PrepareMedia, request: Request, session=DB):
    h, actor, admin = _media_actor(request, session, handover_id, write=True)
    _media_write(h, actor, admin, body.kind)
    if (body.kind == "VEHICLE_VIDEO") != (body.contentType == "video/mp4"):
        raise Problem(422, "MEDIA_TYPE_NOT_ALLOWED")
    if body.kind != "VEHICLE_VIDEO" and body.sizeBytes > PHOTO_LIMIT:
        raise Problem(413, "MEDIA_TOO_LARGE")
    states = dict(h.get("media_state_json") or {})
    if any(kind != body.kind and slot.get("clientFileId") == body.clientFileId for kind, slot in states.items()):
        raise Problem(409, "REQUEST_KEY_REUSED")
    slot = states.get(body.kind)
    if slot and slot.get("clientFileId") == body.clientFileId:
        if slot["contentType"] != body.contentType or slot["sizeBytes"] != body.sizeBytes:
            raise Problem(409, "REQUEST_KEY_REUSED")
        if slot["status"] == "READY":
            return {"status": "success", "upload": {"uploadId": slot["uploadId"], "status": "READY"}}
    elif slot and slot["status"] == "READY":
        raise Problem(409, "HANDOVER_CLOSED")
    else:
        upload_id = str(uuid.uuid4())
        slot = {"uploadId": upload_id, "clientFileId": body.clientFileId, "contentType": body.contentType,
            "sizeBytes": body.sizeBytes, "status": "UPLOADING",
            "temporaryKey": "handover-upload-tmp/" + h["handover_id"] + "/" + upload_id + "/file." + MIME_EXTENSIONS[body.contentType]}
    expires = now() + timedelta(seconds=request.app.state.handover_media.ttl)
    slot = {**slot, "expiresAt": expires.isoformat()}
    upload = request.app.state.handover_media.prepare(slot["temporaryKey"], body.contentType, body.sizeBytes)
    states[body.kind] = slot
    save(request, session, h, media_state_json=states)
    return {"status": "success", "upload": {"uploadId": slot["uploadId"], "kind": body.kind,
            "method": "POST", "url": upload["url"], "fields": upload["fields"], "expiresAt": iso(request, expires)}}


@router.post("/api/v1/nadree/rental/handovers/{handover_id}/media/uploads/{upload_id}/complete", response_model=HandoverResult)
@router.post("/nadreego/handovers/{handover_id}/media/uploads/{upload_id}/complete", response_model=HandoverResult)
def complete_media(handover_id: str, upload_id: str, body: EmptyCommand, request: Request, session=DB):
    h, actor, admin = _media_actor(request, session, handover_id, write=True)
    states = dict(h.get("media_state_json") or {})
    found = [(kind, slot) for kind, slot in states.items() if slot.get("uploadId") == upload_id]
    if not found:
        raise Problem(409, "MEDIA_UPLOAD_NOT_FOUND")
    kind, slot = found[0]
    if (kind == "VEHICLE_VIDEO") == admin:
        raise Problem(403, "PERMISSION_DENIED")
    if admin:
        assignee(h, actor)
    if slot["status"] != "READY":
        _media_write(h, actor, admin, kind)
        if slot["status"] != "UPLOADING":
            raise Problem(409, "MEDIA_UPLOAD_NOT_FOUND")
        final_key = "handover-media/" + h["spot_master_id"] + "/" + h["handover_id"] + "/" + upload_id + "/file." + MIME_EXTENSIONS[slot["contentType"]]
        result = request.app.state.handover_media.finalize(slot, final_key)
        states[kind] = {**slot, **result, "status": "READY"}
        save(request, session, h, media_state_json=states, **{SLOTS[kind][1]: final_key})
        recalculate(request, session, h)
    return {"status": "success", "item": resource(request, session, h, admin_id=actor if admin else None)}


@router.get("/api/v1/nadree/rental/handovers/{handover_id}/media", response_model=HandoverMediaResult)
@router.get("/nadreego/handovers/{handover_id}/media", response_model=HandoverMediaResult)
def get_media(handover_id: str, request: Request, session=DB):
    h, _, _ = _media_actor(request, session, handover_id)
    adapter = request.app.state.handover_media
    items = [{"assetId": slot["uploadId"], "kind": kind, "contentType": slot["contentType"],
        "durationSeconds": slot.get("durationSeconds"), "url": adapter.url(slot["key"]),
        "expiresAt": iso(request, now() + timedelta(seconds=adapter.ttl))}
        for kind, slot in (h.get("media_state_json") or {}).items() if slot.get("status") == "READY"]
    return {"status": "success", "handoverId": h["handover_id"], "items": items}


@router.get("/api/v1/nadree/user/accommodation-history", response_model=AccommodationHistory)
def accommodation_history(request: Request, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100), session=DB):
    user = user_principal(request, session)
    h, c = table(request), request.app.state.db.table("MSP_RENTAL_CONTRACT")
    used = session.execute(select(h.c.accommodation_location_enc, c.c.actual_start_time)
        .join(c, c.c.handover_id == h.c.handover_id).where(h.c.uid_token == user.uid_token,
            c.c.uid_token == user.uid_token, c.c.actual_start_time.is_not(None), c.c.contract_status != "CANCELED")
        .order_by(c.c.actual_start_time.desc(), c.c.rental_contract_id)).mappings()
    addresses = {}
    for row in used:
        address = decrypt(request.app.state.settings, row["accommodation_location_enc"])
        if address and address not in addresses:
            addresses[address] = iso(request, row["actual_start_time"])
    items = [{"accommodationLocation": address, "lastUsedAt": at} for address, at in addresses.items()]
    return {"status": "success", "items": items[(page - 1) * pageSize:page * pageSize], "page": page,
            "pageSize": pageSize, "totalCount": len(items), "hasNext": page * pageSize < len(items)}
