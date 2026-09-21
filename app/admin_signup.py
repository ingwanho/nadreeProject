"""Public administrator account creation and Nadree rental signup requests."""

import uuid

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import lock_email, require_columns, transaction
from app.errors import Problem
from app.responses import AdminSignupResult
from app.schemas import AdminSignup
from app.security import PRIMARY, check_contract, in_subtree, now, password_hash, roles, encrypted_phone

router = APIRouter(prefix="/nadreego/admin", tags=["W01 Accounts"])
DB = Depends(transaction, scope="function")


def _normalized_email(value):
    try:
        return validate_email(str(value), check_deliverability=False).normalized.casefold()
    except EmailNotValidError:
        raise Problem(422, "INVALID_EMAIL") from None


def _limited(request, subject):
    ip = request.client.host if request.client else "unknown"
    request.app.state.limiter.check("admin-signup:ip:" + ip, limit=10, seconds=300)
    request.app.state.limiter.check("admin-signup:subject:" + subject.casefold(), limit=5, seconds=3600)


def _representative_for_target(session, db, target, email):
    """Return the active primary admin allowed to approve the target spot."""
    admins, mapping, role = db.table("MSP_ADMIN"), db.table("MSP_ADMIN_ROLE"), db.table("MSP_ROLE")
    query = (select(admins).join(mapping, mapping.c.admin_id == admins.c.admin_id)
             .join(role, role.c.role_code == mapping.c.role_code)
             .where(admins.c.is_active == 1, mapping.c.role_code == PRIMARY, role.c.is_active == 1,
                    admins.c.email == email))
    rows = session.execute(query.with_for_update()).mappings().all()
    matches = []
    spots = db.table("MSP_SPOT_MASTER")
    for row in rows:
        root_id = row.get("primary_spot_master_id")
        if not root_id:
            continue
        root = session.execute(select(spots).where(spots.c.spot_master_id == root_id,
                                                    spots.c.is_active == 1)).mappings().first()
        if root and in_subtree(root, target):
            matches.append((dict(row), dict(root)))
    if len(matches) != 1:
        raise Problem(404 if not rows else 409, "REPRESENTATIVE_NOT_FOUND" if not rows else "REPRESENTATIVE_AMBIGUOUS")
    return matches[0]


def _target_spot(request, session, body):
    db = request.app.state.db
    master, rent = db.table("MSP_SPOT_MASTER"), db.table("MSP_SPOT_RENT")
    if body.inviteCode:
        row = session.execute(select(master, rent.c.invite_code).join(rent, rent.c.spot_master_id == master.c.spot_master_id)
                              .where(rent.c.invite_code == body.inviteCode, master.c.is_active == 1)
                              .with_for_update()).mappings().first()
        if not row:
            raise Problem(404, "INVITE_CODE_NOT_FOUND")
        target = dict(row)
    else:
        target = None

    if target is None:
        representative_email = _normalized_email(body.representativeEmail)
        admins, mapping, role = db.table("MSP_ADMIN"), db.table("MSP_ADMIN_ROLE"), db.table("MSP_ROLE")
        row = session.execute(
            select(admins).join(mapping, mapping.c.admin_id == admins.c.admin_id).join(role, role.c.role_code == mapping.c.role_code)
            .where(admins.c.email == representative_email, admins.c.is_active == 1,
                   mapping.c.role_code == PRIMARY, role.c.is_active == 1).with_for_update()
        ).mappings().all()
        if len(row) != 1 or not row[0].get("primary_spot_master_id"):
            raise Problem(404 if not row else 409, "REPRESENTATIVE_NOT_FOUND" if not row else "REPRESENTATIVE_AMBIGUOUS")
        target = session.execute(select(master).where(master.c.spot_master_id == row[0]["primary_spot_master_id"],
                                                       master.c.is_active == 1).with_for_update()).mappings().first()
        if not target:
            raise Problem(404, "SPOT_NOT_FOUND")
        return dict(target), dict(row[0])

    if body.representativeEmail:
        representative_email = _normalized_email(body.representativeEmail)
        representative, root = _representative_for_target(session, db, target, representative_email)
    else:
        # A code alone is accepted only when exactly one active primary owns its subtree.
        admins, mapping, role = db.table("MSP_ADMIN"), db.table("MSP_ADMIN_ROLE"), db.table("MSP_ROLE")
        rows = session.execute(select(admins).join(mapping, mapping.c.admin_id == admins.c.admin_id)
            .join(role, role.c.role_code == mapping.c.role_code)
            .where(admins.c.is_active == 1, mapping.c.role_code == PRIMARY, role.c.is_active == 1)
            .with_for_update()).mappings().all()
        matches = []
        for row in rows:
            root_id = row.get("primary_spot_master_id")
            root = session.execute(select(master).where(master.c.spot_master_id == root_id,
                                                        master.c.is_active == 1)).mappings().first() if root_id else None
            if root and in_subtree(root, target):
                matches.append((dict(row), dict(root)))
        if len(matches) != 1:
            raise Problem(409, "REPRESENTATIVE_REQUIRED")
        representative, root = matches[0]
    return target, representative


@router.post("/signup", response_model=AdminSignupResult, status_code=201)
def signup(body: AdminSignup, request: Request, session: Session = DB):
    email = _normalized_email(body.email)
    _limited(request, email)
    db = request.app.state.db
    target, _representative = _target_spot(request, session, body)
    check_contract(session, db, target, request.app.state.settings)

    admins = db.table("MSP_ADMIN")
    lock_email(session, email)
    rows = session.execute(select(admins).where(or_(admins.c.email == email, admins.c.login_id == body.loginId))
                           .with_for_update()).mappings().all()
    if len(rows) > 1:
        raise Problem(409, "ACCOUNT_IDENTITY_AMBIGUOUS")
    existing = dict(rows[0]) if rows else None
    if existing and existing["email"] and existing["email"].casefold() != email and existing["login_id"] == body.loginId:
        raise Problem(409, "LOGIN_ID_IN_USE")
    if existing and existing["email"] and existing["email"].casefold() == email and existing["login_id"] != body.loginId:
        raise Problem(409, "EMAIL_IN_USE")
    if existing and not existing.get("is_active"):
        raise Problem(409, "APPLICANT_ACCOUNT_UNAVAILABLE")
    if existing and roles(session, db, existing["admin_id"]) & {"rental_primary_admin", "rental_manager"}:
        raise Problem(409, "APPLICANT_ALREADY_RENTAL_ADMIN")

    if existing:
        admin_id = existing["admin_id"]
    else:
        admin_id = str(uuid.uuid4())
        values = {"admin_id": admin_id, "login_id": body.loginId, "email": email,
                  "admin_name": body.name, "password_hash": password_hash(body.password.get_secret_value()),
                  "account_type": "manager", "mfa_method": "none", "is_active": 1,
                  "contract_id": None, "primary_spot_master_id": None}
        if body.phone is not None:
            values["phone"] = encrypted_phone(request.app.state.settings, body.phone)
        if "is_legacy" in admins.c:
            values["is_legacy"] = 0
        require_columns(admins, values)
        session.execute(admins.insert().values(**values))

    pending = db.table("MSP_RENTAL_ADMIN_REQUEST")
    duplicate = session.execute(select(pending).where(
        pending.c.spot_master_id == target["spot_master_id"],
        or_(pending.c.email == email, pending.c.admin_id == admin_id)).with_for_update()).mappings().first()
    if duplicate:
        raise Problem(409, "ADMIN_REQUEST_ALREADY_EXISTS")

    request_id = str(uuid.uuid4())
    current = now()
    session.execute(pending.insert().values(request_id=request_id, spot_master_id=target["spot_master_id"],
                                             admin_id=admin_id, email=email, status="REQUESTED", requested_at=current,
                                             reviewed_at=None, reviewed_by_admin_id=None))
    if body.inviteCode:
        rent = db.table("MSP_SPOT_RENT")
        result = session.execute(rent.update().where(rent.c.spot_master_id == target["spot_master_id"],
                                                       rent.c.invite_code == body.inviteCode)
                                 .values(invite_code=None, updated_at=current))
        if result.rowcount != 1:
            raise Problem(409, "INVITE_CODE_ALREADY_USED")
    return {"status": "success", "adminId": admin_id, "requestId": request_id,
            "spotMasterId": target["spot_master_id"], "requestStatus": "REQUESTED"}
