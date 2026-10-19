from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.db import transaction
from app.errors import Problem
from app.headers import bearer
from app.rental_common import by_number, context, editable_spot, fleet, resolve_spot, rows
from app.rental_inputs import PriceChange, TierCreate, TierRange
from app.responses import Status
from app.security import now

router = APIRouter(tags=["W04 Pricing"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


class TierView(BaseModel):
    minCc: int
    maxCc: int
    price: int
    type: str
    spotCode: str | None


class TierList(Status):
    tiers: list[TierView]
    effectiveTiers: list[TierView]


def load_tiers(request, session, spot):
    t = request.app.state.db.table("MSP_RENTAL_TIER")
    return rows(session, t, or_((t.c.spot_master_id.is_(None)) & (t.c.tier_type == "BASE"),
                               (t.c.spot_master_id == spot) & (t.c.tier_type == "BASIC")))


def daily_price(item, tiers):
    rv, model = item["rental"], item["model"]
    if rv["price_type"] == "PREMIUM":
        price = rv["premium_daily_price"]
        return price if price is not None and price >= 0 else None
    if rv["price_type"] != "BASIC" or rv["premium_daily_price"] is not None or model is None or model["cc"] is None:
        return None
    matches = [t for t in tiers if t["min_cc"] <= model["cc"] <= t["max_cc"]]
    base = [t for t in matches if t["tier_type"] == "BASE"]
    basic = [t for t in matches if t["tier_type"] == "BASIC"]
    if len(base) != 1 or len(basic) > 1:
        return None
    if basic and not base[0]["min_cc"] <= basic[0]["min_cc"] <= basic[0]["max_cc"] <= base[0]["max_cc"]:
        return None
    price = (basic or base)[0]["price"]
    return price if price >= 0 else None


def tier_view(row, code):
    return dict(minCc=row["min_cc"], maxCc=row["max_cc"], price=row["price"], type=row["tier_type"],
                spotCode=code if row["spot_master_id"] is not None else None)


@router.post("/nadreego/vehicle/priceChange", response_model=Status)
def change_price(body: PriceChange, request: Request, session: Session = DB):
    _, root = context(request, session, write=True)
    vehicle = by_number(fleet(request, session, root, lock=True), body.vehicleNumber)
    t = request.app.state.db.table("MSP_RENTAL_VEHICLE")
    session.execute(update(t).where(t.c.vehicle_id == vehicle["vehicle"]["vehicle_id"]).values(
        price_type=body.priceType, premium_daily_price=body.priceInfo, updated_at=now()))
    return {"status": "success"}


@router.post("/nadreego/shop/tierCreate", description="BASIC 단건 또는 1~100개 배열. 배열은 동일 지점만 허용하며 전체 성공 또는 전체 롤백됩니다. 동일 cc 구간은 수정, 새 구간은 추가하고 생략한 기존 티어는 유지합니다. 부분 겹침은 409 TIER_RANGE_OVERLAP입니다.")
def create_tier(body: TierCreate | Annotated[list[TierCreate], Field(min_length=1, max_length=100)], request: Request, session: Session = DB):
    actor, root = context(request, session, write=True)
    entries = body if isinstance(body, list) else [body]
    if len({entry.spotCode for entry in entries}) != 1:
        raise Problem(422, "TIER_BATCH_SPOT_MISMATCH")
    if len({(entry.minCc, entry.maxCc) for entry in entries}) != len(entries):
        raise Problem(422, "TIER_BATCH_DUPLICATE_RANGE")
    spot = editable_spot(request, session, actor, root, entries[0].spotCode)
    result = [_save_tier(entry, request, session, spot) for entry in entries]
    return {"status": "success", **({"tiers": result} if isinstance(body, list) else {"tier": result[0]})}


def _save_tier(body, request, session, spot):
    t = request.app.state.db.table("MSP_RENTAL_TIER")
    tiers = load_tiers(request, session, spot["spot_master_id"])
    bases = [r for r in tiers if r["tier_type"] == "BASE" and r["min_cc"] <= body.minCc <= body.maxCc <= r["max_cc"]]
    if len(bases) != 1:
        raise Problem(409, "TIER_BASE_NOT_UNIQUE")
    overlaps = [r for r in tiers if r["tier_type"] == "BASIC" and r["min_cc"] <= body.maxCc and r["max_cc"] >= body.minCc]
    if overlaps and (len(overlaps) != 1 or (overlaps[0]["min_cc"], overlaps[0]["max_cc"]) != (body.minCc, body.maxCc)):
        raise Problem(409, "TIER_RANGE_OVERLAP")
    values = dict(spot_master_id=spot["spot_master_id"], tier_type="BASIC", min_cc=body.minCc, max_cc=body.maxCc, price=body.price)
    if overlaps:
        session.execute(update(t).where(t.c.spot_master_id == spot["spot_master_id"], t.c.tier_type == "BASIC",
            t.c.min_cc == body.minCc, t.c.max_cc == body.maxCc).values(price=body.price))
    else:
        session.execute(t.insert().values(**values))
    return {**tier_view(values, spot["unit_code"]), "action": "UPDATED" if overlaps else "CREATED"}


def effective_tiers(tiers, code):
    """Split BASE only where this spot has a BASIC override; do not persist splits."""
    result = []
    for base in sorted((t for t in tiers if t["tier_type"] == "BASE"), key=lambda t: t["min_cc"]):
        cursor = base["min_cc"]
        basics = sorted((t for t in tiers if t["tier_type"] == "BASIC"
                         and base["min_cc"] <= t["min_cc"] <= t["max_cc"] <= base["max_cc"]),
                        key=lambda t: t["min_cc"])
        for basic in basics:
            if cursor < basic["min_cc"]:
                result.append(tier_view({**base, "min_cc": cursor, "max_cc": basic["min_cc"] - 1}, code))
            result.append(tier_view(basic, code))
            cursor = basic["max_cc"] + 1
        if cursor <= base["max_cc"]:
            result.append(tier_view({**base, "min_cc": cursor}, code))
    return result


@router.get("/nadreego/shop/tierCreate", response_model=TierList, description="spotCode 생략/null은 공통 BASE만, 지정하면 해당 지점 BASE+BASIC 설정을 tiers에 반환합니다. effectiveTiers는 BASIC이 있는 구간만 대체한 실제 적용 구간이며 빈 구간은 BASE입니다. 다른 지점 BASIC은 상속하지 않습니다. PREMIUM 차량 고정 단가는 별도입니다.")
def list_tiers(request: Request, spotCode: str | None = Query(None, min_length=1, max_length=60), session: Session = DB):
    _, root = context(request, session)
    spot = resolve_spot(request, session, root, spotCode) if spotCode else None
    tiers = load_tiers(request, session, spot["spot_master_id"] if spot else None)
    if not spot:
        tiers = [t for t in tiers if t["tier_type"] == "BASE"]
    tiers.sort(key=lambda r: (r["tier_type"] != "BASE", r["min_cc"], r["max_cc"]))
    code = spot["unit_code"] if spot else None
    return {"status": "success", "tiers": [tier_view(t, code) for t in tiers],
            "effectiveTiers": effective_tiers(tiers, code)}


@router.post("/nadreego/shop/tierDelete")
def delete_tier(body: TierRange, request: Request, session: Session = DB):
    _, root = context(request, session, write=True)
    t = request.app.state.db.table("MSP_RENTAL_TIER")
    condition = (t.c.spot_master_id == root["spot_master_id"]) & (t.c.tier_type == "BASIC") & (t.c.min_cc == body.minCc) & (t.c.max_cc == body.maxCc)
    found = session.execute(select(t).where(condition)).all()
    if len(found) != 1:
        raise Problem(404 if not found else 409, "TIER_NOT_FOUND")
    session.execute(delete(t).where(condition))
    return {"status": "success"}
