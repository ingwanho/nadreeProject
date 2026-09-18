import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.db import lock_email, require_columns, transaction
from app.errors import Problem
from app.headers import bearer, fcm_header, refresh_header
from app.responses import ProfileResult, SignedIn, SpotResult, Status, Tokens
from app.schemas import Email, FcmToken, Login, Profile, SpotCode
from app.security import (DUMMY_HASH, GENERAL, PRIMARY, SESSION_MARKER, check_contract, lock_account,
                          encrypted_phone, fingerprint, now, password_hash, principal,
                          roles, sign_access, verify_password)

router = APIRouter(prefix="/nadreego/admin", tags=["W01 Accounts"])
DB = Depends(transaction, scope="function")


def public_admin(row, granted):
    return {"adminId": row["admin_id"], "name": row["admin_name"], "email": row["email"],
            "role": PRIMARY if PRIMARY in granted else GENERAL,
            "spotMasterId": row.get("primary_spot_master_id")}


def limited(request, operation, subject):
    ip = request.client.host if request.client else "unknown"
    request.app.state.limiter.check(f"{operation}:ip:{ip}", limit=30)
    request.app.state.limiter.check(f"{operation}:subject:{subject.casefold()}", limit=10)


@router.post("/login", response_model=SignedIn)
def login(body: Login, request: Request, session: Session = DB):
    limited(request, "login", body.email)
    settings, db = request.app.state.settings, request.app.state.db
    # Validate signing configuration before performing any successful-login writes.
    sign_access(settings, "configuration-check", "configuration-check", 0)
    admins = db.table("MSP_ADMIN")
    rows = session.execute(select(admins).where(or_(admins.c.login_id == body.email,
            admins.c.email == body.email)).with_for_update()).mappings().all()
    row = rows[0] if len(rows) == 1 else None
    password_ok = verify_password(body.password.get_secret_value(), row["password_hash"] if row else DUMMY_HASH)
    if not row or not password_ok or not row["is_active"]:
        raise Problem(401, "INVALID_CREDENTIALS")
    # Do not let a second service bypass existing account MFA policy.
    if row.get("mfa_method", "none") != "none":
        raise Problem(403, "MFA_REQUIRED")
    granted = roles(session, db, row["admin_id"])
    if not granted & {PRIMARY, GENERAL}:
        raise Problem(403, "RENTAL_ROLE_REQUIRED")
    current = now()
    token_id = str(uuid.uuid4())
    raw = "nadree.rt." + secrets.token_urlsafe(48)
    tokens = db.table("MSP_REFRESH_TOKEN")
    active_sessions = session.execute(select(tokens).where(
        tokens.c.admin_id == row["admin_id"], tokens.c.user_agent == SESSION_MARKER,
        tokens.c.revoked_at.is_(None), tokens.c.expires_at > current)
        .order_by(tokens.c.issued_at.asc(), tokens.c.token_id.asc()).with_for_update()).mappings().all()
    # 관리자 계정은 최대 3대의 활성 기기를 허용한다. 네 번째 로그인 시 가장 오래된 세션을 폐기한다.
    for old in active_sessions[:max(0, len(active_sessions) - 2)]:
        session.execute(update(tokens).where(tokens.c.token_id == old["token_id"],
            tokens.c.revoked_at.is_(None)).values(revoked_at=current))
    session.execute(tokens.insert().values(token_id=token_id, admin_id=row["admin_id"],
        token_hash=fingerprint(raw), user_agent=SESSION_MARKER, issued_at=current,
        expires_at=current + timedelta(days=settings.refresh_days)))
    values = {"last_login_at": current}
    if body.fcmToken is not None:
        values.update(fcm_token=body.fcmToken, fcm_token_updated_at=current)
    require_columns(admins, values)
    session.execute(update(admins).where(admins.c.admin_id == row["admin_id"]).values(**values))
    auth_time = current.replace(tzinfo=timezone.utc).timestamp()
    return {"status": "success", "accessToken": sign_access(settings, row["admin_id"], token_id, auth_time),
            "refreshToken": raw, "admin": public_admin(row, granted)}


def refresh_row(request, session, locked=True):
    raw = request.headers.get("X-Refresh-Token", "")
    if not raw.startswith("nadree.rt.") or len(raw) > 256:
        raise Problem(401, "INVALID_REFRESH_TOKEN")
    table = request.app.state.db.table("MSP_REFRESH_TOKEN")
    query = select(table).where(table.c.token_hash == fingerprint(raw), table.c.user_agent == SESSION_MARKER,
            table.c.revoked_at.is_(None), table.c.expires_at > now())
    if locked:
        query = query.with_for_update()
    row = session.execute(query).mappings().first()
    if not row:
        raise Problem(401, "INVALID_REFRESH_TOKEN")
    return table, row


@router.get("/refresh", response_model=Tokens, dependencies=[Depends(refresh_header)])
def refresh(request: Request, session: Session = DB):
    limited(request, "refresh", request.headers.get("X-Refresh-Token", ""))
    _, initial = refresh_row(request, session, locked=False)
    lock_account(request, session, initial["admin_id"])
    table, row = refresh_row(request, session)
    raw = "nadree.rt." + secrets.token_urlsafe(48)
    result = session.execute(update(table).where(table.c.token_id == row["token_id"], table.c.token_hash == row["token_hash"],
            table.c.revoked_at.is_(None)).values(token_hash=fingerprint(raw)))
    if result.rowcount != 1:
        raise Problem(401, "INVALID_REFRESH_TOKEN")
    # Preserve original authentication time and absolute session expiration.
    issued = row["issued_at"].replace(tzinfo=timezone.utc).timestamp()
    access = sign_access(request.app.state.settings, row["admin_id"], row["token_id"], issued)
    return {"status": "success", "accessToken": access, "refreshToken": raw}


@router.get("/logout", response_model=Status, dependencies=[bearer, Depends(refresh_header), Depends(fcm_header)])
def logout(request: Request, session: Session = DB):
    actor = principal(request, session)
    lock_account(request, session, actor.admin["admin_id"], actor.session_id)
    table, row = refresh_row(request, session)
    if row["token_id"] != actor.session_id or row["admin_id"] != actor.admin["admin_id"]:
        raise Problem(401, "TOKEN_PAIR_MISMATCH")
    # 로그아웃은 현재 세션만 폐기한다. FCM 토큰은 다음 로그인·알림에 재사용할 수 있도록 보관한다.
    session.execute(update(table).where(table.c.token_id == actor.session_id).values(revoked_at=now()))
    return {"status": "success"}


@router.post("/fcmToken", response_model=Status, dependencies=[bearer])
def fcm_token(body: FcmToken, request: Request, session: Session = DB):
    actor = principal(request, session)
    lock_account(request, session, actor.admin["admin_id"], actor.session_id)
    admins = request.app.state.db.table("MSP_ADMIN")
    require_columns(admins, {"fcm_token": body.fcmToken, "fcm_token_updated_at": now()})
    session.execute(update(admins).where(admins.c.admin_id == actor.admin["admin_id"], admins.c.is_active == 1)
                    .values(fcm_token=body.fcmToken, fcm_token_updated_at=now()))
    return {"status": "success"}


@router.post("/spotcheck", response_model=SpotResult, dependencies=[bearer])
def spot_check(body: SpotCode, request: Request, session: Session = DB):
    actor = principal(request, session)
    limited(request, "spotcheck", actor.admin["admin_id"])
    db = request.app.state.db
    spot, rent = db.table("MSP_SPOT_MASTER"), db.table("MSP_SPOT_RENT")
    row = session.execute(select(spot, rent.c.delivery_service_type).join(rent, spot.c.spot_master_id == rent.c.spot_master_id)
        .where(rent.c.invite_code == body.spotCode, spot.c.is_active == 1)).mappings().first()
    if not row:
        raise Problem(404, "INVITE_CODE_NOT_FOUND")
    check_contract(session, db, row, request.app.state.settings)
    # Knowledge of an invite code does not grant membership or consume it here.
    return {"status": "success", "spotMasterId": row["spot_master_id"], "spotName": row["spot_name"],
            "unitCode": row["unit_code"], "isDeliverySupported": row["delivery_service_type"] != "NONE"}


@router.post("/update", response_model=ProfileResult, dependencies=[bearer, Depends(refresh_header)])
def profile(body: Profile, request: Request, session: Session = DB):
    actor = principal(request, session)
    actor.admin = dict(lock_account(request, session, actor.admin["admin_id"], actor.session_id))
    if not body.model_fields_set or any(getattr(body, key) is None for key in body.model_fields_set):
        raise Problem(422, "EMPTY_OR_NULL_UPDATE")
    settings, db = request.app.state.settings, request.app.state.db
    admins = db.table("MSP_ADMIN")
    if {"password", "email"} & body.model_fields_set:
        _, token = refresh_row(request, session)
        if token["token_id"] != actor.session_id:
            raise Problem(401, "TOKEN_PAIR_MISMATCH")
        if datetime.now(timezone.utc).timestamp() - actor.auth_time > 300:
            raise Problem(401, "REAUTHENTICATION_REQUIRED")
    values = {}
    if body.name is not None:
        values["admin_name"] = body.name
    if body.email is not None:
        from email_validator import EmailNotValidError, validate_email
        try:
            email = validate_email(body.email, check_deliverability=False).normalized
        except EmailNotValidError:
            raise Problem(422, "INVALID_EMAIL") from None
        lock_email(session, email)
        if session.execute(select(admins.c.admin_id).where(admins.c.admin_id != actor.admin["admin_id"],
                or_(admins.c.email == email, admins.c.login_id == email))).first():
            raise Problem(409, "EMAIL_IN_USE")
        values["email"] = email
    if body.phone is not None:
        values["phone"] = encrypted_phone(settings, body.phone)
        if getattr(admins.c.phone.type, "length", 0) and admins.c.phone.type.length < len(values["phone"]):
            raise Problem(503, "PHONE_STORAGE_MAPPING_REQUIRED")
    if body.fcmToken is not None:
        values.update(fcm_token=body.fcmToken, fcm_token_updated_at=now())
    if body.password is not None:
        values["password_hash"] = password_hash(body.password.get_secret_value())
    require_columns(admins, values)
    session.execute(update(admins).where(admins.c.admin_id == actor.admin["admin_id"]).values(**values))
    if body.password is not None or body.email is not None:
        tokens = db.table("MSP_REFRESH_TOKEN")
        session.execute(update(tokens).where(tokens.c.admin_id == actor.admin["admin_id"],
                tokens.c.revoked_at.is_(None)).values(revoked_at=now()))
    return {"status": "success", "adminId": actor.admin["admin_id"],
            "name": values.get("admin_name", actor.admin["admin_name"]), "email": values.get("email", actor.admin["email"])}


@router.post("/findpswd", response_model=Status)
def find_password(body: Email, request: Request, session: Session = DB):
    limited(request, "password-reset", body.email)
    request.app.state.limiter.check("password-reset:cooldown:" + body.email.casefold(), limit=1, seconds=300)
    request.app.state.mailer.check_configuration()
    admins = request.app.state.db.table("MSP_ADMIN")
    rows = session.execute(select(admins).where(admins.c.email == body.email).with_for_update()).mappings().all()
    # Keep the approved email-only contract; do not reveal unknown or ambiguous accounts.
    if len(rows) != 1 or not rows[0]["is_active"]:
        return {"status": "success"}
    row = rows[0]
    if not roles(session, request.app.state.db, row["admin_id"]) & {PRIMARY, GENERAL}:
        return {"status": "success"}
    request.app.state.limiter.check("password-reset:account:" + row["admin_id"], limit=1, seconds=300)
    password = secrets.token_urlsafe(24)
    session.execute(update(admins).where(admins.c.admin_id == row["admin_id"]).values(password_hash=password_hash(password)))
    tokens = request.app.state.db.table("MSP_REFRESH_TOKEN")
    session.execute(update(tokens).where(tokens.c.admin_id == row["admin_id"], tokens.c.revoked_at.is_(None)).values(revoked_at=now()))
    # SMTP failure rolls back DB writes. SMTP acceptance and DB commit are not atomic.
    request.app.state.mailer.send(row["email"], password)
    return {"status": "success"}
