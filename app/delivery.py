from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import transaction
from app.errors import Problem
from app.headers import bearer
from app.rental_common import context, resolve_spot
from app.rental_inputs import Delivery, DeliveryDelete
from app.security import now

router = APIRouter(tags=["W05 Delivery"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


@router.post("/nadreego/shop/delivery")
def save_delivery(body: Delivery, request: Request, session: Session = DB):
    _, root = context(request, session, write=True, representative=True)
    spot = resolve_spot(request, session, root, body.spotCode, lock=True)
    db = request.app.state.db
    region, t = db.table("MSP_DELIVERY_REGION"), db.table("MSP_SPOT_DELIVERY_REGION")
    if not session.scalar(select(region.c.delivery_region_id).where(region.c.delivery_region_id == body.deliveryRegionId, region.c.is_active == 1)):
        raise Problem(404, "DELIVERY_REGION_NOT_FOUND")
    existing = session.execute(select(t).where(t.c.spot_master_id == spot["spot_master_id"],
        t.c.delivery_region_id == body.deliveryRegionId).with_for_update()).mappings().first()
    values = dict(is_delivery_enabled=body.isDeliveryEnabled, start_delivery_fee=body.startDeliveryFee,
                  return_delivery_fee=body.returnDeliveryFee, updated_at=now())
    if "memo" in body.model_fields_set:
        values["memo"] = body.memo
    if existing:
        ident = existing["spot_delivery_region_id"]
        session.execute(update(t).where(t.c.spot_delivery_region_id == ident).values(**values))
    else:
        ident = session.execute(t.insert().values(spot_master_id=spot["spot_master_id"],
            delivery_region_id=body.deliveryRegionId, created_at=now(), **values)).inserted_primary_key[0]
    return dict(status=True, spotDeliveryRegionId=ident, deliveryRegionId=body.deliveryRegionId,
                isDeliveryEnabled=body.isDeliveryEnabled, startDeliveryFee=body.startDeliveryFee, returnDeliveryFee=body.returnDeliveryFee)


@router.get("/nadreego/shop/delivery/regions")
def regions(request: Request, countryCode: str = Query("KR", min_length=2, max_length=10),
            page: int = Query(1, ge=1), pageSize: int = Query(100, ge=1, le=100), session: Session = DB):
    context(request, session)
    t = request.app.state.db.table("MSP_DELIVERY_REGION")
    where = (t.c.country_code == countryCode.upper()) & (t.c.is_active == 1)
    total = session.scalar(select(func.count()).select_from(t).where(where))
    rows = session.execute(select(t).where(where).order_by(t.c.sort_order, t.c.delivery_region_id)
        .offset((page - 1) * pageSize).limit(pageSize)).mappings()
    return dict(status=True, items=[dict(deliveryRegionId=r["delivery_region_id"], countryCode=r["country_code"],
        regionName=r["region_name"], parentRegionId=r["parent_region_id"], regionLevel=r["region_level"], regionCode=r["region_code"],
        sortOrder=r["sort_order"], isActive=bool(r["is_active"])) for r in rows], page=page, pageSize=pageSize, totalCount=total)


@router.get("/nadreego/shop/delivery")
def list_delivery(request: Request, spotCode: str = Query(..., min_length=1, max_length=60),
                  page: int = Query(1, ge=1), pageSize: int = Query(100, ge=1, le=100), session: Session = DB):
    _, root = context(request, session)
    spot = resolve_spot(request, session, root, spotCode)
    db = request.app.state.db
    t, r = db.table("MSP_SPOT_DELIVERY_REGION"), db.table("MSP_DELIVERY_REGION")
    source = t.join(r, r.c.delivery_region_id == t.c.delivery_region_id)
    where = t.c.spot_master_id == spot["spot_master_id"]
    total = session.scalar(select(func.count()).select_from(source).where(where))
    result = session.execute(select(t, r.c.region_name, r.c.region_code).select_from(source).where(where)
        .order_by(r.c.sort_order, t.c.spot_delivery_region_id).offset((page - 1) * pageSize).limit(pageSize)).mappings()
    return dict(status=True, items=[dict(spotDeliveryRegionId=x["spot_delivery_region_id"], deliveryRegionId=x["delivery_region_id"],
        regionName=x["region_name"], regionCode=x["region_code"], isDeliveryEnabled=bool(x["is_delivery_enabled"]),
        startDeliveryFee=x["start_delivery_fee"], returnDeliveryFee=x["return_delivery_fee"], memo=x["memo"]) for x in result],
        page=page, pageSize=pageSize, totalCount=total)


@router.post("/nadreego/shop/deliveryDelete")
def delete_delivery(body: DeliveryDelete, request: Request, session: Session = DB):
    _, root = context(request, session, write=True, representative=True)
    t = request.app.state.db.table("MSP_SPOT_DELIVERY_REGION")
    row = session.execute(select(t).where(t.c.spot_delivery_region_id == body.spotDeliveryRegionId)).mappings().first()
    if not row:
        raise Problem(404, "DELIVERY_SETTING_NOT_FOUND")
    resolve_spot(request, session, root, row["spot_master_id"], lock=True)
    session.execute(update(t).where(t.c.spot_delivery_region_id == body.spotDeliveryRegionId)
        .values(is_delivery_enabled=False, updated_at=now()))
    return {"status": True}
