from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.db import transaction
from app.errors import Problem
from app.headers import bearer
from app.rental_common import by_number, context, fleet, resolve_spot, rows
from app.rental_inputs import PriceChange, TierCreate, TierRange
from app.responses import Status
from app.security import now

router = APIRouter(tags=["W04 Pricing"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


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


@router.post("/nadreego/shop/tierCreate")
def create_tier(body: TierCreate, request: Request, session: Session = DB):
    _, root = context(request, session, write=True, representative=True)
    spot = resolve_spot(request, session, root, body.spotCode, lock=True)
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
    return {"status": "success", "tier": {**tier_view(values, spot["unit_code"]), "action": "UPDATED" if overlaps else "CREATED"}}


@router.get("/nadreego/shop/tierCreate")
def list_tiers(request: Request, spotCode: str | None = Query(None, min_length=1, max_length=60), session: Session = DB):
    _, root = context(request, session)
    spot = resolve_spot(request, session, root, spotCode) if spotCode else None
    tiers = load_tiers(request, session, spot["spot_master_id"] if spot else None)
    if not spot:
        tiers = [t for t in tiers if t["tier_type"] == "BASE"]
    tiers.sort(key=lambda r: (r["tier_type"] != "BASE", r["min_cc"], r["max_cc"]))
    return {"status": "success", "tiers": [tier_view(t, spot["unit_code"] if spot else None) for t in tiers]}


@router.post("/nadreego/shop/tierDelete")
def delete_tier(body: TierRange, request: Request, session: Session = DB):
    _, root = context(request, session, write=True, representative=True)
    t = request.app.state.db.table("MSP_RENTAL_TIER")
    condition = (t.c.spot_master_id == root["spot_master_id"]) & (t.c.tier_type == "BASIC") & (t.c.min_cc == body.minCc) & (t.c.max_cc == body.maxCc)
    found = session.execute(select(t).where(condition)).all()
    if len(found) != 1:
        raise Problem(404 if not found else 409, "TIER_NOT_FOUND")
    session.execute(delete(t).where(condition))
    return {"status": "success"}
