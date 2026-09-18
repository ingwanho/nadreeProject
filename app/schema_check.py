from sqlalchemy import select

from app.errors import Problem
from app.security import GENERAL, PRIMARY


REQUIRED = {
    "MSP_ADMIN": "admin_id login_id email phone password_hash admin_name mfa_method contract_id primary_spot_master_id is_active last_login_at fcm_token fcm_token_updated_at",
    "MSP_ROLE": "role_code role_name is_active",
    "MSP_ADMIN_ROLE": "admin_id role_code assigned_at expires_at",
    "MSP_REFRESH_TOKEN": "token_id admin_id token_hash user_agent issued_at expires_at revoked_at",
    "MSP_CONTRACT": "contract_id status start_date end_date",
    "MSP_ADMIN_SPOT_SCOPE": "admin_id spot_master_id spot_id unit_code access_type granted_at granted_by",
    "MSP_SPOT_MASTER": "spot_master_id contract_id org_id region_id local_id spot_id org_name region_name local_name unit_code spot_name hierarchy_level address zip_code biz_reg_num phone lat lng contract_start contract_end is_active",
    "MSP_SPOT_RENT": "spot_master_id legacy_spot_code delivery_service_type invite_code created_at updated_at introduction contact_email",
    "MSP_RENTAL_ADMIN_REQUEST": "request_id spot_master_id admin_id email status requested_at reviewed_at reviewed_by_admin_id",
    "MSP_ORG": "org_id contract_id org_name unit_code address phone",
    "MSP_REGION": "region_id contract_id org_id region_name unit_code address phone",
    "MSP_LOCAL": "local_id contract_id org_id local_name unit_code address phone",
    "MSP_SPOT": "spot_id contract_id org_id spot_name unit_code address phone",
}


def check_schema(db, connection):
    for name, columns in REQUIRED.items():
        if not set(columns.split()).issubset(db.table(name).c.keys()):
            raise Problem(503, "SCHEMA_MAPPING_REQUIRED")
    admins = db.table("MSP_ADMIN")
    if getattr(admins.c.fcm_token.type, "length", 0) < 512:
        raise Problem(503, "SCHEMA_MAPPING_REQUIRED")
    table = db.table("MSP_ROLE")
    active = set(connection.scalars(select(table.c.role_code).where(table.c.is_active == 1)))
    if not {PRIMARY, GENERAL}.issubset(active):
        raise Problem(503, "RENTAL_ROLE_NOT_CONFIGURED")
    limitations = ["MFA_FLOW_NOT_IMPLEMENTED"]
    if getattr(admins.c.phone.type, "length", 0) and admins.c.phone.type.length < 200:
        limitations.append("PHONE_STORAGE_MAPPING_REQUIRED")
    rent = db.table("MSP_SPOT_RENT")
    if any(getattr(rent.c[name].type, "length", 0) and rent.c[name].type.length < length
           for name, length in [("introduction", 500), ("contact_email", 200)]):
        limitations.append("SHOP_PROFILE_MAPPING_REQUIRED")
    return limitations
