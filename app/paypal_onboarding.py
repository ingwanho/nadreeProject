"""Verified seller linking using existing spot columns, without onboarding storage."""
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

import jwt
from pydantic import Field
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update

from app.db import transaction
from app.errors import Problem
from app.headers import bearer
from app.rental_common import context, editable_spot
from app.schemas import Body, Identifier
from app.security import now
from app.responses import Status

router = APIRouter(prefix="/nadreego/shop/paypal-onboarding", tags=["PayPal onboarding"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


class Target(Body):
    spotMasterId: Identifier


class Verify(Target):
    state: str = Field(min_length=1, max_length=4096)


class Started(Status):
    state: str
    actionUrl: str
    expiresAt: datetime
    paymentEnvironment: str


class Verified(Status):
    spotMasterId: str
    merchantId: str
    paymentEnvironment: str


def target(body, request, session):
    actor, root = context(request, session, write=True, representative=True)
    spot = editable_spot(request, session, actor, root, body.spotMasterId)
    # Seller linking is narrower than hierarchy management: direct primary only.
    if spot["spot_master_id"] != root["spot_master_id"]:
        raise Problem(403, "PAYPAL_DIRECT_PRIMARY_REQUIRED")
    request.app.state.limiter.check("paypal-onboarding:" + actor.admin["admin_id"], limit=10, seconds=60)
    return actor, spot


@router.post("/start", response_model=Started, summary="미연결 지점 대표의 PayPal 연결 URL 발급")
def start(body: Target, request: Request, session=DB):
    actor, _ = target(body, request, session)
    table, row = spot_row(body, request, session)
    if row["paypal_merchant_id"]:
        raise Problem(409, "SHOP_PAYPAL_ALREADY_CONNECTED")
    settings = request.app.state.settings
    callback = settings.paypal_onboarding_return_url
    parsed = urlsplit(callback)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise Problem(503, "PAYPAL_ONBOARDING_RETURN_URL_REQUIRED")
    secret = settings.jwt_secret.get_secret_value()
    if len(secret.encode()) < 32:
        raise Problem(503, "AUTH_NOT_CONFIGURED")
    at = now().replace(tzinfo=timezone.utc)
    expires = at + timedelta(minutes=30)
    tracking = str(uuid.uuid4())
    state = jwt.encode({"sub": actor.admin["admin_id"], "sid": actor.session_id,
        "spot": body.spotMasterId, "env": settings.paypal_environment, "jti": tracking,
        "iss": settings.jwt_issuer, "aud": "nadree-paypal-onboarding", "iat": at, "exp": expires}, secret, algorithm="HS256")
    action_url, _ = request.app.state.paypal.onboarding_url(tracking, callback + "?" + urlencode({"state": state}))
    return {"status": "success", "state": state, "actionUrl": action_url,
            "expiresAt": expires, "paymentEnvironment": settings.paypal_environment}


def spot_row(body, request, session):
    table = request.app.state.db.table("MSP_SPOT_RENT")
    if not {"paypal_merchant_id", "paypal_environment"}.issubset(table.c.keys()):
        raise Problem(503, "PAYPAL_MERCHANT_SCHEMA_UPDATE_REQUIRED")
    row = session.execute(select(table).where(table.c.spot_master_id == body.spotMasterId).with_for_update()).mappings().first()
    if not row:
        raise Problem(404, "RENTAL_SPOT_NOT_CONFIGURED")
    return table, row


@router.post("/verify", response_model=Verified, summary="PayPal에서 판매자 ID 확인 후 지점 컬럼에 저장",
             description="start의 state와 같은 관리자 로그인 세션이 필요합니다. state는 30분 유효하며 브라우저 merchantId는 받지 않습니다. 완료 후 예약 승인은 별도 재요청합니다.")
def verify(body: Verify, request: Request, session=DB):
    actor, _ = target(body, request, session)
    table, row = spot_row(body, request, session)
    settings = request.app.state.settings
    try:
        claims = jwt.decode(body.state, settings.jwt_secret.get_secret_value(), algorithms=["HS256"],
            issuer=settings.jwt_issuer, audience="nadree-paypal-onboarding",
            options={"require": ["sub", "sid", "spot", "env", "jti", "iat", "exp"]})
        if (claims["sub"] != actor.admin["admin_id"] or claims["sid"] != actor.session_id
                or claims["spot"] != body.spotMasterId or claims["env"] != settings.paypal_environment
                or not isinstance(claims["jti"], str)):
            raise ValueError
    except jwt.ExpiredSignatureError:
        raise Problem(410, "PAYPAL_ONBOARDING_STATE_EXPIRED") from None
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise Problem(400, "PAYPAL_ONBOARDING_STATE_INVALID") from None
    seller = request.app.state.paypal.seller_by_tracking(claims["jti"])
    if row["paypal_merchant_id"] and (row["paypal_merchant_id"] != seller or row["paypal_environment"] != settings.paypal_environment):
        raise Problem(409, "SHOP_PAYPAL_ALREADY_CONNECTED")
    session.execute(update(table).where(table.c.spot_master_id == body.spotMasterId).values(
        paypal_merchant_id=seller, paypal_environment=settings.paypal_environment, updated_at=now()))
    return {"status": "success", "spotMasterId": body.spotMasterId, "merchantId": seller,
            "paymentEnvironment": settings.paypal_environment}


def process_merchant_event(db, client, stored, event):
    """Recheck revocation against PayPal; never link a spot from browser/webhook input."""
    seller = (event.get("resource") or {}).get("merchant_id")
    spots = db.table("MSP_SPOT_RENT")
    environment = client.settings.paypal_environment
    with db.engine.connect() as conn:
        linked = conn.scalar(select(spots.c.spot_master_id).where(
            spots.c.paypal_merchant_id == seller, spots.c.paypal_environment == environment).limit(1)) if seller else None
    revoked = False
    if linked:
        try:
            client.verify_merchant(seller)
        except Problem as error:
            if error.code != "PAYPAL_MERCHANT_NOT_READY":
                raise
            revoked = True
    events = db.table("MSP_PAYPAL_WEBHOOK_EVENT")
    with db.engine.begin() as conn:
        if revoked:
            conn.execute(update(spots).where(spots.c.paypal_merchant_id == seller,
                spots.c.paypal_environment == environment).values(
                    paypal_merchant_id=None, paypal_environment=None, updated_at=now()))
        conn.execute(update(events).where(events.c.webhook_event_id == stored["webhook_event_id"])
            .values(processing_status="PROCESSED", processed_at=now(), updated_at=now()))
