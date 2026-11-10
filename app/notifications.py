"""Durable shop-wide inbox, independent of personal chat read positions."""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin_customers import customer_scope
from app.db import transaction
from app.errors import Problem
from app.headers import bearer
from app.rental_common import iso
from app.security import now

router = APIRouter(prefix="/nadreego/notifications", tags=["Shop notifications"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


class Notification(BaseModel):
    notificationId: int
    shopId: str
    eventType: str
    message: str
    targetType: str
    targetId: str
    createdAt: str
    isRead: bool
    readAt: str | None


class NotificationList(BaseModel):
    status: str
    items: list[Notification]
    page: int
    pageSize: int
    totalCount: int
    hasNext: bool


class NotificationRead(Notification):
    status: str


class UnreadCount(BaseModel):
    status: str
    shopId: str
    unreadCount: int


def record_notification(db, session, shop_id, event, target_type, target_id, event_key):
    table = db.table("MSP_RENTAL_NOTIFICATION")
    if session.scalar(select(table.c.notification_id).where(table.c.event_key == event_key)):
        return
    try:
        with session.begin_nested():
            session.execute(table.insert().values(spot_master_id=shop_id, event_type=event,
                target_type=target_type, target_id=str(target_id), event_key=event_key, created_at=now()))
    except IntegrityError:
        if not session.scalar(select(table.c.notification_id).where(table.c.event_key == event_key)):
            raise


def view(request, row):
    return {"notificationId": row["notification_id"], "shopId": row["spot_master_id"],
            "eventType": row["event_type"], "message":
                "Tasks have been transferred to the primary administrator after the assigned administrator's account was deleted."
                if row["event_type"] == "RESERVATION_MANAGER_TRANSFERRED" else "You have a new work notification.",
            "targetType": row["target_type"], "targetId": row["target_id"],
            "createdAt": iso(request, row["created_at"]), "isRead": row["read_at"] is not None,
            "readAt": iso(request, row["read_at"])}


def payment_notification(db, session, payment, event, key):
    if payment["reservation_id"]:
        table = db.table("MSP_RESERVATION")
        shop = session.scalar(select(table.c.spot_master_id).where(table.c.reservation_id == payment["reservation_id"]))
    else:
        table = db.table("MSP_RENTAL_CONTRACT")
        shop = session.scalar(select(table.c.pickup_spot_master_id).where(table.c.rental_contract_id == payment["rental_contract_id"]))
    if shop:
        record_notification(db, session, shop, event, "PAYMENT", payment["payment_id"], key)


@router.get("", response_model=NotificationList, summary="List shared shop notifications", description="Lists business notifications without personal information. Notifications are not automatically deleted by a retention period. The relevant business API revalidates permissions when the target details are opened.")
def notifications(request: Request, shopId: str = Query(..., min_length=1, max_length=36),
                  page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
                  isRead: bool | None = None, eventType: str | None = Query(None, max_length=50), session: Session = DB):
    spots = customer_scope(request, session, shopId)
    table = request.app.state.db.table("MSP_RENTAL_NOTIFICATION")
    condition = table.c.spot_master_id.in_(spots)
    if isRead is not None:
        condition &= table.c.read_at.is_not(None) if isRead else table.c.read_at.is_(None)
    if eventType:
        condition &= table.c.event_type == eventType
    total = session.scalar(select(func.count()).select_from(table).where(condition))
    rows = session.execute(select(table).where(condition).order_by(table.c.notification_id.desc())
        .offset((page - 1) * pageSize).limit(pageSize)).mappings()
    return {"status": "success", "items": [view(request, row) for row in rows], "page": page,
            "pageSize": pageSize, "totalCount": total, "hasNext": page * pageSize < total}


@router.get("/unread-count", response_model=UnreadCount, summary="Get the shared shop unread notification count")
def unread(request: Request, shopId: str = Query(..., min_length=1, max_length=36), session: Session = DB):
    spots = customer_scope(request, session, shopId)
    table = request.app.state.db.table("MSP_RENTAL_NOTIFICATION")
    count = session.scalar(select(func.count()).select_from(table).where(
        table.c.spot_master_id.in_(spots), table.c.read_at.is_(None)))
    return {"status": "success", "shopId": shopId, "unreadCount": count}


@router.post("/{notification_id}/read", response_model=NotificationRead, summary="Mark a notification as read for all shop staff")
def mark_read(notification_id: int, request: Request, session: Session = DB):
    spots = customer_scope(request, session)
    table = request.app.state.db.table("MSP_RENTAL_NOTIFICATION")
    row = session.execute(select(table).where(table.c.notification_id == notification_id,
        table.c.spot_master_id.in_(spots)).with_for_update()).mappings().first()
    if not row:
        raise Problem(404, "NOTIFICATION_NOT_FOUND")
    at = row["read_at"] or now()
    if row["read_at"] is None:
        session.execute(update(table).where(table.c.notification_id == notification_id,
            table.c.read_at.is_(None)).values(read_at=at))
    return {"status": "success", **view(request, dict(row, read_at=at))}
