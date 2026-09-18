import re
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.db import require_columns, transaction
from app.errors import Problem
from app.headers import bearer
from app.responses import Admins, Applicants, CreatedSpot, Hierarchy, PrimaryResult, ShopResult, Status
from app.schemas import AdminId, RequestAction, Shop, SpotCreate
from app.security import (GENERAL, PRIMARY, SESSION_MARKER, active_spot, check_contract, in_subtree,
                          now, principal, roles)

router = APIRouter(tags=["W02 Organizations and admins"], dependencies=[bearer])
DB = Depends(transaction, scope="function")


def representative(request, session):
    actor = principal(request, session)
    root = active_spot(request, session, actor, representative=True, lock=True)
    return actor, root


def member(session, db, admin_id, root):
    table = db.table("MSP_ADMIN")
    row = session.execute(select(table).where(table.c.admin_id == admin_id, table.c.is_active == 1,
        table.c.primary_spot_master_id == root["spot_master_id"]).with_for_update()).mappings().first()
    if not row:
        raise Problem(404, "ADMIN_NOT_FOUND")
    scope = db.table("MSP_ADMIN_SPOT_SCOPE")
    if not session.execute(select(scope.c.admin_id).where(scope.c.admin_id == admin_id,
        scope.c.spot_master_id == root["spot_master_id"], scope.c.access_type == "manage")).first():
        raise Problem(409, "ADMIN_SCOPE_INCONSISTENT")
    return dict(row)


def set_role(session, db, admin_id, value):
    mapping = db.table("MSP_ADMIN_ROLE")
    session.execute(delete(mapping).where(mapping.c.admin_id == admin_id, mapping.c.role_code.in_([PRIMARY, GENERAL])))
    session.execute(mapping.insert().values(admin_id=admin_id, role_code=value, assigned_at=now()))


@router.post("/nadreego/admin/roleChange", response_model=PrimaryResult)
def change_role(body: AdminId, request: Request, session: Session = DB):
    actor, root = representative(request, session)
    db = request.app.state.db
    target = member(session, db, body.adminId, root)
    if body.adminId == actor.admin["admin_id"]:
        return {"status": "success", "primaryAdminId": body.adminId}
    if roles(session, db, target["admin_id"]) & {PRIMARY, GENERAL} != {GENERAL}:
        raise Problem(409, "TARGET_ROLE_INVALID")
    admins, mapping = db.table("MSP_ADMIN"), db.table("MSP_ADMIN_ROLE")
    primaries = session.scalars(select(admins.c.admin_id).join(mapping, admins.c.admin_id == mapping.c.admin_id)
        .where(admins.c.primary_spot_master_id == root["spot_master_id"], admins.c.is_active == 1,
               mapping.c.role_code == PRIMARY, or_(mapping.c.expires_at.is_(None), mapping.c.expires_at > now()))).all()
    if primaries != [actor.admin["admin_id"]]:
        raise Problem(409, "PRIMARY_ADMIN_INCONSISTENT")
    set_role(session, db, actor.admin["admin_id"], GENERAL)
    set_role(session, db, target["admin_id"], PRIMARY)
    return {"status": "success", "primaryAdminId": target["admin_id"]}


@router.get("/nadreego/shop/admin", response_model=Admins)
def list_admins(request: Request, session: Session = DB):
    actor = principal(request, session)
    root = active_spot(request, session, actor)
    db = request.app.state.db
    table = db.table("MSP_ADMIN")
    rows = session.execute(select(table).where(table.c.primary_spot_master_id == root["spot_master_id"],
        table.c.is_active == 1).order_by(table.c.admin_id)).mappings().all()
    items = []
    for row in rows:
        granted = roles(session, db, row["admin_id"])
        if granted & {PRIMARY, GENERAL}:
            items.append({"adminId": row["admin_id"], "name": row["admin_name"], "email": row["email"],
                          "role": PRIMARY if PRIMARY in granted else GENERAL})
    return {"status": "success", "admin": items}


@router.post("/nadreego/shop/adminDelete", response_model=Status)
def delete_admin(body: AdminId, request: Request, session: Session = DB):
    actor, root = representative(request, session)
    db = request.app.state.db
    target = member(session, db, body.adminId, root)
    if roles(session, db, target["admin_id"]) & {PRIMARY, GENERAL} != {GENERAL}:
        raise Problem(409, "PRIMARY_ADMIN_CANNOT_BE_REMOVED")
    # Remove rental membership, not a shared account or its unrelated web roles.
    mapping = db.table("MSP_ADMIN_ROLE")
    session.execute(delete(mapping).where(mapping.c.admin_id == body.adminId, mapping.c.role_code == GENERAL))
    tokens = db.table("MSP_REFRESH_TOKEN")
    session.execute(update(tokens).where(tokens.c.admin_id == body.adminId, tokens.c.user_agent == SESSION_MARKER,
        tokens.c.revoked_at.is_(None)).values(revoked_at=now()))
    admins = db.table("MSP_ADMIN")
    session.execute(update(admins).where(admins.c.admin_id == body.adminId)
                    .values(fcm_token=None, fcm_token_updated_at=now()))
    return {"status": "success"}


@router.post("/nadreego/shop/update", response_model=ShopResult)
def update_shop(body: Shop, request: Request, session: Session = DB):
    actor, root = representative(request, session)
    if not body.model_fields_set or any(getattr(body, name) is None for name in body.model_fields_set):
        raise Problem(422, "EMPTY_OR_NULL_UPDATE")
    db = request.app.state.db
    master, rent = db.table("MSP_SPOT_MASTER"), db.table("MSP_SPOT_RENT")
    values = {column: getattr(body, name) for name, column in
              [("shopName", "spot_name"), ("location", "address"), ("contact", "phone")]
              if name in body.model_fields_set}
    if body.shopName is not None and "unit_name" in master.c:
        values["unit_name"] = body.shopName
    extra = {column: getattr(body, name) for name, column in
             [("introduction", "introduction"), ("email", "contact_email"), ("deliveryServiceType", "delivery_service_type")]
             if name in body.model_fields_set}
    require_columns(master, values)
    require_columns(rent, extra)
    rent_row = session.execute(select(rent).where(rent.c.spot_master_id == root["spot_master_id"])).mappings().first()
    if not rent_row:
        raise Problem(409, "RENTAL_SPOT_NOT_CONFIGURED")
    if values:
        session.execute(update(master).where(master.c.spot_master_id == root["spot_master_id"]).values(**values))
        # Keep normalized hierarchy names/contact data consistent with the master.
        level = root["hierarchy_level"]
        if level in ["org", "region", "local", "spot"]:
            normalized = db.table("MSP_" + level.upper())
            normalized_values = {(level + "_name" if k == "spot_name" else k): v for k, v in values.items() if k != "unit_name"}
            require_columns(normalized, normalized_values)
            result = session.execute(update(normalized).where(normalized.c[level + "_id"] == root[level + "_id"])
                                     .values(**normalized_values))
            if result.rowcount != 1:
                raise Problem(409, "ORGANIZATION_MAPPING_INCONSISTENT")
            if body.shopName is not None and level in ["org", "region", "local"]:
                session.execute(update(master).where(master.c[level + "_id"] == root[level + "_id"],
                    master.c.contract_id == root["contract_id"]).values(**{level + "_name": body.shopName}))
    if extra:
        session.execute(update(rent).where(rent.c.spot_master_id == root["spot_master_id"]).values(**extra))
    return {"status": "success", "spotMasterId": root["spot_master_id"],
            "deliveryServiceType": extra.get("delivery_service_type", rent_row["delivery_service_type"])}


@router.get("/api/v1/organizations/spots/hierarchy", response_model=Hierarchy)
def hierarchy(request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
              search: str = Query("", max_length=100), unit_type: str = Query("", max_length=20),
              is_active: int = Query(-1, ge=-1, le=1), has_manager: int = Query(-1, ge=-1, le=1),
              session: Session = DB):
    actor = principal(request, session)
    root = active_spot(request, session, actor)
    db = request.app.state.db
    table = db.table("MSP_SPOT_MASTER")
    admins, mapping, role = db.table("MSP_ADMIN"), db.table("MSP_ADMIN_ROLE"), db.table("MSP_ROLE")
    scope = db.table("MSP_ADMIN_SPOT_SCOPE")
    managers = (select(admins.c.primary_spot_master_id.label("spot_id"), func.min(admins.c.admin_name).label("manager_name"))
        .join(mapping, admins.c.admin_id == mapping.c.admin_id).join(role, role.c.role_code == mapping.c.role_code)
        .join(scope, (scope.c.admin_id == admins.c.admin_id) & (scope.c.spot_master_id == admins.c.primary_spot_master_id))
        .where(admins.c.is_active == 1, mapping.c.role_code == PRIMARY, role.c.is_active == 1, scope.c.access_type == "manage",
               or_(mapping.c.expires_at.is_(None), mapping.c.expires_at > now()))
        .group_by(admins.c.primary_spot_master_id).subquery())
    source = table.outerjoin(managers, table.c.spot_master_id == managers.c.spot_id)
    # A segment delimiter prevents ORG01 from matching ORG010.
    condition = (table.c.contract_id == root["contract_id"]) & table.c.unit_code.startswith(root["unit_code"] + "-", autoescape=True)
    if search:
        condition &= or_(table.c.spot_name.contains(search, autoescape=True), table.c.unit_code.contains(search, autoescape=True),
                         managers.c.manager_name.contains(search, autoescape=True))
    if unit_type:
        condition &= table.c.hierarchy_level == unit_type
    if is_active != -1:
        condition &= table.c.is_active == is_active
    if has_manager != -1:
        condition &= managers.c.spot_id.is_not(None) if has_manager else managers.c.spot_id.is_(None)
    total = session.scalar(select(func.count()).select_from(source).where(condition))
    rows = session.execute(select(table, managers.c.manager_name).select_from(source).where(condition).order_by(table.c.unit_code, table.c.spot_master_id)
                           .offset(offset).limit(limit)).mappings().all()
    keys = ["spot_master_id", "unit_code", "spot_name", "hierarchy_level", "org_name", "region_name", "is_active"]
    return {"items": [{**{k: row.get(k) for k in keys}, "is_active": bool(row["is_active"]),
                       "manager_name": row["manager_name"]} for row in rows],
            "total": total}


@router.post("/api/v1/organizations/spots", response_model=CreatedSpot)
def create_spot(body: SpotCreate, request: Request, session: Session = DB):
    actor, root = representative(request, session)
    if body.unit_type == "org":
        raise Problem(403, "TOP_LEVEL_ORG_FORBIDDEN")
    db = request.app.state.db
    table = db.table("MSP_SPOT_MASTER")
    parent = session.execute(select(table).where(table.c.spot_master_id == body.parent_spot_id,
        table.c.is_active == 1).with_for_update()).mappings().first()
    if not parent or not in_subtree(root, parent):
        raise Problem(404, "PARENT_SPOT_NOT_FOUND")
    check_contract(session, db, parent, request.app.state.settings)
    end = body.contract_end or parent["contract_end"]
    start = body.contract_start or parent["contract_start"]
    if ((start and end and start > end) or (parent["contract_end"] and end and end > parent["contract_end"])
            or (parent["contract_start"] and start and start < parent["contract_start"])):
        raise Problem(422, "CONTRACT_DATES_INVALID")
    prefix = {"region": "R", "local": "L", "spot": "SP", "team": "T", "agency": "A"}[body.unit_type]
    stem = parent["unit_code"] + "-" + prefix
    codes = session.scalars(select(table.c.unit_code).where(table.c.unit_code.startswith(stem, autoescape=True))).all()
    pattern = re.compile(re.escape(stem) + r"(\d+)$")
    sequence = max([int(m[1]) for code in codes if (m := pattern.fullmatch(code))] + [0]) + 1
    unit_code = stem + f"{sequence:02d}"
    ident = str(uuid.uuid4())
    values = {"spot_master_id": ident, "contract_id": parent["contract_id"], "org_id": parent["org_id"],
              "org_name": parent.get("org_name"), "region_id": parent.get("region_id"), "local_id": parent.get("local_id"),
              "region_name": parent.get("region_name"), "local_name": parent.get("local_name"),
              "spot_id": None, "unit_code": unit_code, "spot_name": body.spot_name,
              "hierarchy_level": body.unit_type, "phone": body.phone, "biz_reg_num": body.biz_reg_num,
              "address": " ".join(x for x in [body.address, body.address_detail] if x) or None,
              "zip_code": body.zip_code, "lat": body.lat, "lng": body.lng,
              "contract_start": start, "contract_end": end, "is_active": 1}
    if "unit_name" in table.c:
        values["unit_name"] = body.spot_name
    if body.unit_type in ["region", "local", "spot"]:
        values[body.unit_type + "_id"] = ident
    if body.unit_type == "region":
        values.update(region_name=body.spot_name, local_id=None, local_name=None)
    if body.unit_type == "local":
        values.update(local_name=body.spot_name)
    require_columns(table, values)
    if body.unit_type in ["region", "local", "spot"]:
        normal = db.table("MSP_" + body.unit_type.upper())
        normalized = {k: v for k, v in values.items() if k in normal.c}
        normalized[body.unit_type + "_name"] = body.spot_name
        require_columns(normal, normalized)
        session.execute(normal.insert().values(**normalized))
    session.execute(table.insert().values(**values))
    rent = db.table("MSP_SPOT_RENT")
    session.execute(rent.insert().values(spot_master_id=ident, delivery_service_type="NONE"))
    return {"spot_id": ident, "unit_code": unit_code, "spot_name": body.spot_name,
            "hierarchy_level": body.unit_type, "phone": body.phone, "biz_reg_num": body.biz_reg_num,
            "address": values["address"], "zip_code": body.zip_code, "lat": body.lat, "lng": body.lng,
            "contract_start": start, "contract_end": end, "is_active": True}


@router.get("/nadreego/shop/adminRequest", response_model=Applicants)
def admin_requests(request: Request, session: Session = DB):
    actor = principal(request, session)
    root = active_spot(request, session, actor, representative=True)
    db = request.app.state.db
    pending, admins = db.table("MSP_RENTAL_ADMIN_REQUEST"), db.table("MSP_ADMIN")
    rows = session.execute(select(pending.c.email, admins.c.admin_name)
        .select_from(pending.outerjoin(admins, admins.c.admin_id == pending.c.admin_id))
        .where(pending.c.spot_master_id == root["spot_master_id"], pending.c.status == "REQUESTED")
        .order_by(pending.c.requested_at, pending.c.request_id)).mappings().all()
    return {"status": "success", "admins": [{"email": row["email"], "name": row["admin_name"]} for row in rows]}


@router.post("/nadreego/shop/adminRequestAction", response_model=Status)
def admin_request_action(body: RequestAction, request: Request, session: Session = DB):
    actor, root = representative(request, session)
    db = request.app.state.db
    pending = db.table("MSP_RENTAL_ADMIN_REQUEST")
    row = session.execute(select(pending).where(pending.c.spot_master_id == root["spot_master_id"],
        pending.c.email == str(body.email).casefold()).with_for_update()).mappings().first()
    if not row:
        raise Problem(404, "ADMIN_REQUEST_NOT_FOUND")
    if row["status"] != "REQUESTED":
        raise Problem(409, "ADMIN_REQUEST_ALREADY_PROCESSED")
    current = now()
    if body.action == "APPROVE":
        # The account lock also serializes approvals for the same applicant at different spots.
        admins = db.table("MSP_ADMIN")
        target = session.execute(select(admins).where(admins.c.admin_id == row["admin_id"])
                                 .with_for_update()).mappings().first()
        if not target or not target["is_active"]:
            raise Problem(409, "APPLICANT_ACCOUNT_UNAVAILABLE")
        if not target["email"] or target["email"].casefold() != row["email"]:
            raise Problem(409, "APPLICANT_EMAIL_CHANGED")
        if (target["primary_spot_master_id"] not in [None, root["spot_master_id"]]
                or target["contract_id"] not in [None, root["contract_id"]]):
            raise Problem(409, "APPLICANT_MEMBERSHIP_CONFLICT")
        mapping, role = db.table("MSP_ADMIN_ROLE"), db.table("MSP_ROLE")
        if session.execute(select(mapping.c.admin_id).where(mapping.c.admin_id == target["admin_id"],
                mapping.c.role_code.in_([PRIMARY, GENERAL]))).first():
            raise Problem(409, "APPLICANT_ALREADY_RENTAL_ADMIN")
        if not session.execute(select(role.c.role_code).where(role.c.role_code == GENERAL,
                role.c.is_active == 1)).first():
            raise Problem(503, "RENTAL_ROLE_NOT_CONFIGURED")
        session.execute(update(admins).where(admins.c.admin_id == target["admin_id"])
            .values(primary_spot_master_id=root["spot_master_id"], contract_id=root["contract_id"]))
        session.execute(mapping.insert().values(admin_id=target["admin_id"], role_code=GENERAL, assigned_at=current))
        scope = db.table("MSP_ADMIN_SPOT_SCOPE")
        if not session.execute(select(scope.c.admin_id).where(scope.c.admin_id == target["admin_id"],
                scope.c.spot_master_id == root["spot_master_id"], scope.c.access_type == "manage")).first():
            session.execute(scope.insert().values(admin_id=target["admin_id"], spot_master_id=root["spot_master_id"],
                spot_id=root["spot_id"], unit_code=root["unit_code"], access_type="manage",
                granted_at=current, granted_by=actor.admin["admin_id"]))
    result = session.execute(update(pending).where(pending.c.request_id == row["request_id"],
        pending.c.status == "REQUESTED").values(status="APPROVED" if body.action == "APPROVE" else "REJECTED",
            reviewed_at=current, reviewed_by_admin_id=actor.admin["admin_id"]))
    if result.rowcount != 1:
        raise Problem(409, "ADMIN_REQUEST_ALREADY_PROCESSED")
    return {"status": "success"}
