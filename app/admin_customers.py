"""Read-only customer views restricted to the administrator's rental scope."""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import exists, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.db import transaction
from app.errors import Problem
from app.headers import bearer
from app.rental_common import context, iso, resolve_spot
from app.security import PRIMARY, roles

router = APIRouter(prefix="/nadreego/customers", tags=["Admin customers"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


class CustomerSummary(BaseModel):
    customerId: str
    name: str | None
    usageStatus: str


class CustomerList(BaseModel):
    status: str
    items: list[CustomerSummary]
    page: int
    pageSize: int
    totalCount: int
    hasNext: bool


class CustomerDetail(BaseModel):
    customerId: str
    name: str | None
    contact: str | None
    nationality: str | None
    gender: str | None
    age: int | None


class CustomerDetailResult(BaseModel):
    status: str
    customer: CustomerDetail


class HistoricalPayment(BaseModel):
    paymentId: int
    amount: float
    currency: str
    refundedAmount: float
    refundStatus: str
    refundPercentage: int | None
    cancellationRequestedByType: str | None
    cancellationRequestedById: str | None


class CustomerHistoryItem(BaseModel):
    reservationId: str | None
    rentalContractId: str | None
    vehicleId: str | None
    vehicleName: str | None
    startAt: str | None
    endAt: str | None
    usageStatus: str
    payments: list[HistoricalPayment]


class CustomerHistory(BaseModel):
    status: str
    items: list[CustomerHistoryItem]
    page: int
    pageSize: int
    totalCount: int
    hasNext: bool


def customer_scope(request, session, spot_id=None):
    actor, root = context(request, session)
    db = request.app.state.db
    primary = PRIMARY in roles(session, db, actor.admin["admin_id"])
    if spot_id:
        target = resolve_spot(request, session, root, spot_id)
        if not primary and target["spot_master_id"] != root["spot_master_id"]:
            raise Problem(403, "SPOT_ACCESS_DENIED")
        return [target["spot_master_id"]]
    if not primary:
        return [root["spot_master_id"]]
    table = db.table("MSP_SPOT_MASTER")
    return list(session.scalars(select(table.c.spot_master_id).where(
        table.c.is_active == 1, table.c.contract_id == root["contract_id"], table.c.org_id == root["org_id"],
        or_(table.c.spot_master_id == root["spot_master_id"],
            table.c.unit_code.startswith(root["unit_code"] + "-", autoescape=True)))))


def relationship(db, users, spots, active=False):
    reservations, contracts = db.table("MSP_RESERVATION"), db.table("MSP_RENTAL_CONTRACT")
    r = select(reservations.c.reservation_id).where(
        reservations.c.uid_token == users.c.uid_token, reservations.c.spot_master_id.in_(spots))
    c = select(contracts.c.rental_contract_id).where(
        contracts.c.uid_token == users.c.uid_token, contracts.c.pickup_spot_master_id.in_(spots))
    if active:
        r = r.where(reservations.c.reservation_status.in_(("REQUESTED", "APPROVED", "HANDED_OVER")))
        c = c.where(contracts.c.contract_status.in_(("ON_RENT", "OVERDUE")))
    return or_(exists(r), exists(c))


def customer_row(request, session, customer_id, spots):
    db = request.app.state.db
    users = db.table("MSP_RENTAL_USER")
    row = session.execute(select(users).where(users.c.uid_token == customer_id,
        relationship(db, users, spots))).mappings().first()
    if not row:
        raise Problem(404, "CUSTOMER_NOT_FOUND")
    return row


@router.get("", response_model=CustomerList, summary="권한 범위 내 고객 목록",
            description="ACTIVE는 진행 요청/승인/인계 예약 또는 대여 중 고객, INACTIVE는 해당 이력이 없는 거래 고객입니다. 계정 탈퇴 상태와 다릅니다.")
def customers(request: Request, spotMasterId: str | None = Query(None, max_length=36),
              search: str = Query("", max_length=100), status: str | None = Query(None, pattern="^(ACTIVE|INACTIVE)$"),
              page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100), session: Session = DB):
    db = request.app.state.db
    spots = customer_scope(request, session, spotMasterId)
    users = db.table("MSP_RENTAL_USER")
    active = relationship(db, users, spots, active=True)
    condition = relationship(db, users, spots)
    if search:
        condition &= or_(users.c.name.contains(search, autoescape=True), users.c.uid_token == search)
    if status:
        condition &= active if status == "ACTIVE" else ~active
    total = session.scalar(select(func.count()).select_from(users).where(condition))
    rows = session.execute(select(users.c.uid_token, users.c.name, active.label("active")).where(condition)
        .order_by(users.c.uid_token).offset((page - 1) * pageSize).limit(pageSize)).mappings()
    return {"status": "success", "items": [{"customerId": r["uid_token"], "name": r["name"],
            "usageStatus": "ACTIVE" if r["active"] else "INACTIVE"} for r in rows],
            "page": page, "pageSize": pageSize, "totalCount": total, "hasNext": page * pageSize < total}


@router.get("/{customer_id}", response_model=CustomerDetailResult, summary="관리자 고객 상세",
            description="연락처는 현재 렌탈 고객 DB에 없으므로 null입니다. 여권·FCM 토큰·세션 정보는 제공하지 않습니다. 제공되지 않은 프로필도 null입니다.")
def detail(customer_id: str, request: Request, spotMasterId: str | None = Query(None, max_length=36), session: Session = DB):
    row = customer_row(request, session, customer_id, customer_scope(request, session, spotMasterId))
    return {"status": "success", "customer": {"customerId": row["uid_token"], "name": row["name"],
            "contact": None, "nationality": row["nationality"], "gender": row["gender"], "age": row["age"]}}


@router.get("/{customer_id}/history", response_model=CustomerHistory, summary="관리자 고객 예약 및 렌탈 이력",
            description="허용 지점의 예약과 예약 없는 렌탈을 조회합니다. 결제는 현재 PayPal 환경에서 paid_at이 있는 결제만 포함하며 미결제 금액은 0입니다.")
def history(customer_id: str, request: Request, spotMasterId: str | None = Query(None, max_length=36),
            page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100), session: Session = DB):
    db = request.app.state.db
    spots = customer_scope(request, session, spotMasterId)
    customer_row(request, session, customer_id, spots)
    r, c, p = (db.table(name) for name in ("MSP_RESERVATION", "MSP_RENTAL_CONTRACT", "MSP_RENTAL_PAYMENT"))
    # Page across both kinds without duplicating reservations already handed over.
    records = union_all(
        select(literal("RESERVATION").label("kind"), r.c.reservation_id.label("id"), r.c.start_datetime.label("start"))
            .where(r.c.uid_token == customer_id, r.c.spot_master_id.in_(spots)),
        select(literal("RENTAL").label("kind"), c.c.rental_contract_id.label("id"), c.c.actual_start_time.label("start"))
            .where(c.c.uid_token == customer_id, c.c.pickup_spot_master_id.in_(spots), c.c.reservation_id.is_(None))).subquery()
    total = session.scalar(select(func.count()).select_from(records))
    selected = session.execute(select(records).order_by(records.c.start.desc(), records.c.kind, records.c.id)
        .offset((page - 1) * pageSize).limit(pageSize)).mappings().all()
    items = []
    for record in selected:
        reservation = session.execute(select(r).where(r.c.reservation_id == record["id"])).mappings().first() if record["kind"] == "RESERVATION" else None
        contract = session.execute(select(c).where(c.c.reservation_id == record["id"] if reservation else c.c.rental_contract_id == record["id"])).mappings().first()
        payments = session.execute(select(p).where(
            p.c.reservation_id == record["id"] if reservation else p.c.rental_contract_id == record["id"],
            p.c.payment_environment == request.app.state.settings.paypal_environment,
            p.c.paid_at.is_not(None)).order_by(p.c.payment_id)).mappings().all()
        models, vehicles = db.table("MSP_VEHICLE_MODEL"), db.table("MSP_RENTAL_VEHICLE")
        model_id = reservation["model_id"] if reservation else session.scalar(select(vehicles.c.model_id).where(vehicles.c.vehicle_id == contract["vehicle_id"]))
        vehicle_name = session.scalar(select(models.c.model_name).where(models.c.model_id == model_id))
        items.append({"reservationId": reservation["reservation_id"] if reservation else None,
            "vehicleName": vehicle_name,
            "rentalContractId": contract["rental_contract_id"] if contract else None,
            "vehicleId": contract["vehicle_id"] if contract else reservation["assigned_vehicle_id"],
            "startAt": iso(request, contract["actual_start_time"] if contract else reservation["start_datetime"]),
            "endAt": iso(request, contract["actual_end_time"] if contract else reservation["end_datetime"]),
            "usageStatus": contract["contract_status"] if contract else reservation["reservation_status"],
            "payments": [{"paymentId": x["payment_id"], "amount": float(x["total_price"]), "currency": x["currency"],
                "refundedAmount": float(x["refunded_amount"]), "refundStatus": x["refund_status"],
                "refundPercentage": x.get("refund_percentage"),
                "cancellationRequestedByType": x.get("cancellation_requested_by_type"),
                "cancellationRequestedById": x.get("cancellation_requested_by_id")} for x in payments]})
    return {"status": "success", "items": items, "page": page, "pageSize": pageSize,
            "totalCount": total, "hasNext": page * pageSize < total}
