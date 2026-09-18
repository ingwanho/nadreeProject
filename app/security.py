import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import bcrypt
import jwt
from cryptography.fernet import Fernet
from redis import Redis, RedisError
from sqlalchemy import or_, select

from app.errors import Problem

PRIMARY = "rental_primary_admin"
GENERAL = "rental_manager"
SESSION_MARKER = "nadree-api/v1"
USER_ACCESS_TYPE = "nadri_user_access"
DUMMY_HASH = bcrypt.hashpw(b"non-user-comparison", bcrypt.gensalt())


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password):
    raw = password.encode()
    if not 8 <= len(raw) <= 72:
        raise Problem(422, "PASSWORD_LENGTH_INVALID")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode()


def verify_password(password, hashed):
    raw = password.encode()
    if len(raw) > 72:
        return False
    try:
        return bcrypt.checkpw(raw, hashed.encode() if isinstance(hashed, str) else hashed)
    except (ValueError, TypeError):
        return False


def sign_access(settings, admin_id, session_id, auth_time):
    secret = settings.jwt_secret.get_secret_value()
    if len(secret.encode()) < 32:
        raise Problem(503, "AUTH_NOT_CONFIGURED")
    current = datetime.now(timezone.utc)
    return jwt.encode({"sub": admin_id, "sid": session_id, "type": "access",
                       "iss": settings.jwt_issuer, "aud": settings.jwt_audience,
                       "iat": current, "exp": current + timedelta(minutes=settings.access_minutes),
                       "auth_time": int(auth_time), "jti": secrets.token_urlsafe(24)}, secret, algorithm="HS256")


def decode_access(settings, token):
    if len(settings.jwt_secret.get_secret_value().encode()) < 32:
        raise Problem(503, "AUTH_NOT_CONFIGURED")
    try:
        claims = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"],
                            issuer=settings.jwt_issuer, audience=settings.jwt_audience,
                            options={"require": ["sub", "sid", "type", "iat", "exp", "jti", "auth_time"]})
        if claims["type"] != "access" or not isinstance(claims["sid"], str) or not isinstance(claims["auth_time"], int):
            raise ValueError
        return claims
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise Problem(401, "AUTH_REQUIRED") from None


def sign_user_access(settings, uid_token, auth_time=None):
    secret = settings.jwt_secret.get_secret_value()
    if len(secret.encode()) < 32:
        raise Problem(503, "AUTH_NOT_CONFIGURED")
    current = datetime.now(timezone.utc)
    auth_time = int(current.timestamp()) if auth_time is None else int(auth_time)
    return jwt.encode({"sub": uid_token, "type": USER_ACCESS_TYPE,
                       "iss": settings.jwt_issuer, "aud": settings.user_jwt_audience,
                       "iat": current, "exp": current + timedelta(minutes=settings.user_access_minutes),
                       "auth_time": auth_time, "jti": secrets.token_urlsafe(24)},
                      secret, algorithm="HS256")


def decode_user_access(settings, token):
    if len(settings.jwt_secret.get_secret_value().encode()) < 32:
        raise Problem(503, "AUTH_NOT_CONFIGURED")
    try:
        claims = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"],
                            issuer=settings.jwt_issuer, audience=settings.user_jwt_audience,
                            options={"require": ["sub", "type", "iat", "exp", "jti", "auth_time"]})
        if claims["type"] != USER_ACCESS_TYPE or not isinstance(claims["sub"], str) or not isinstance(claims["auth_time"], int):
            raise ValueError
        return claims
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise Problem(401, "INVALID_NADRI_USER_TOKEN") from None


@dataclass
class UserPrincipal:
    uid_token: str
    auth_time: int


def user_principal(request, session):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise Problem(401, "INVALID_NADRI_USER_TOKEN")
    claims = decode_user_access(request.app.state.settings, header[7:])
    if len(claims["sub"]) > 36:
        raise Problem(401, "INVALID_NADRI_USER_TOKEN")
    users = request.app.state.db.table("MSP_RENTAL_USER")
    row = session.execute(select(users).where(users.c.uid_token == claims["sub"])).mappings().first()
    if not row:
        raise Problem(401, "INVALID_NADRI_USER_TOKEN")
    revoked = row.get("user_access_revoked_at")
    if revoked is not None and claims["auth_time"] <= int(revoked.replace(tzinfo=timezone.utc).timestamp()):
        raise Problem(401, "INVALID_NADRI_USER_TOKEN")
    return UserPrincipal(claims["sub"], claims["auth_time"])


def roles(session, db, admin_id):
    mapping, role = db.table("MSP_ADMIN_ROLE"), db.table("MSP_ROLE")
    stmt = select(mapping.c.role_code).join(role, mapping.c.role_code == role.c.role_code).where(
        mapping.c.admin_id == admin_id, role.c.is_active == 1,
        or_(mapping.c.expires_at.is_(None), mapping.c.expires_at > now()))
    return set(session.scalars(stmt))


@dataclass
class Principal:
    admin: dict
    session_id: str
    auth_time: int


def principal(request, session):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise Problem(401, "AUTH_REQUIRED")
    claims = decode_access(request.app.state.settings, header[7:])
    db = request.app.state.db
    admins, tokens = db.table("MSP_ADMIN"), db.table("MSP_REFRESH_TOKEN")
    row = session.execute(select(admins).where(admins.c.admin_id == claims["sub"], admins.c.is_active == 1)).mappings().first()
    token = session.execute(select(tokens).where(tokens.c.token_id == claims["sid"], tokens.c.admin_id == claims["sub"],
        tokens.c.user_agent == SESSION_MARKER, tokens.c.revoked_at.is_(None), tokens.c.expires_at > now())).mappings().first()
    if not row or not token:
        raise Problem(401, "AUTH_REQUIRED")
    if row["mfa_method"] != "none":
        raise Problem(403, "MFA_REQUIRED")
    if not roles(session, db, row["admin_id"]) & {PRIMARY, GENERAL}:
        raise Problem(403, "RENTAL_ROLE_REQUIRED")
    return Principal(dict(row), claims["sid"], claims["auth_time"])


def lock_account(request, session, admin_id, session_id=None):
    table = request.app.state.db.table("MSP_ADMIN")
    row = session.execute(select(table).where(table.c.admin_id == admin_id, table.c.is_active == 1)
                          .with_for_update()).mappings().first()
    if not row or not roles(session, request.app.state.db, admin_id) & {PRIMARY, GENERAL}:
        raise Problem(401, "AUTH_REQUIRED")
    if row["mfa_method"] != "none":
        raise Problem(403, "MFA_REQUIRED")
    if session_id is not None:
        tokens = request.app.state.db.table("MSP_REFRESH_TOKEN")
        active = session.execute(select(tokens.c.token_id).where(tokens.c.token_id == session_id,
            tokens.c.admin_id == admin_id, tokens.c.user_agent == SESSION_MARKER,
            tokens.c.revoked_at.is_(None), tokens.c.expires_at > now())).first()
        if not active:
            raise Problem(401, "AUTH_REQUIRED")
    return row


def business_today(settings):
    return datetime.now(timezone.utc).astimezone(ZoneInfo(settings.business_timezone)).date()


def check_contract(session, db, spot, settings):
    today = business_today(settings)
    contracts = db.table("MSP_CONTRACT")
    contract = session.execute(select(contracts).where(contracts.c.contract_id == spot["contract_id"])).mappings().first()
    if not contract or contract["status"] != "active":
        raise Problem(403, "SPOT_CONTRACT_INACTIVE")
    for start, end in [(spot.get("contract_start"), spot.get("contract_end")),
                       (contract["start_date"], contract["end_date"])]:
        if (start and start > today) or (end and end < today):
            raise Problem(403, "SPOT_CONTRACT_INACTIVE")


def active_spot(request, session, actor, representative=False, lock=False):
    db = request.app.state.db
    table = db.table("MSP_SPOT_MASTER")
    root_id = actor.admin.get("primary_spot_master_id")
    if not root_id:
        raise Problem(403, "SPOT_REQUIRED")
    query = select(table).where(table.c.spot_master_id == root_id, table.c.is_active == 1)
    if lock:
        query = query.with_for_update()
    spot = session.execute(query).mappings().first()
    if not spot:
        raise Problem(403, "SPOT_UNAVAILABLE")
    # Re-read after the shared spot lock, not from the token's old role claims.
    admin_table = db.table("MSP_ADMIN")
    fresh = session.execute(select(admin_table).where(admin_table.c.admin_id == actor.admin["admin_id"])).mappings().one()
    if not fresh["is_active"] or fresh["primary_spot_master_id"] != root_id:
        raise Problem(403, "SPOT_ACCESS_DENIED")
    granted = roles(session, db, fresh["admin_id"])
    if representative and PRIMARY not in granted:
        raise Problem(403, "PRIMARY_ADMIN_REQUIRED")
    if not granted & {PRIMARY, GENERAL}:
        raise Problem(403, "RENTAL_ROLE_REQUIRED")
    scope = db.table("MSP_ADMIN_SPOT_SCOPE")
    if not session.execute(select(scope.c.admin_id).where(scope.c.admin_id == fresh["admin_id"],
            scope.c.spot_master_id == root_id, scope.c.access_type == "manage")).first():
        raise Problem(403, "SPOT_ACCESS_DENIED")
    check_contract(session, db, spot, request.app.state.settings)
    return dict(spot)


def in_subtree(root, candidate, include_root=True):
    same_contract = candidate["contract_id"] == root["contract_id"]
    return same_contract and ((include_root and candidate["spot_master_id"] == root["spot_master_id"]) or
                             candidate["unit_code"].startswith(root["unit_code"] + "-"))


class RateLimiter:
    script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"

    def __init__(self, url):
        self.redis = Redis.from_url(url, socket_timeout=3) if url else None

    def check(self, key, limit=10, seconds=60):
        if self.redis is None:
            raise Problem(503, "RATE_LIMIT_NOT_CONFIGURED")
        try:
            count = self.redis.eval(self.script, 1, "nadree:limit:" + fingerprint(key), seconds)
        except RedisError:
            raise Problem(503, "RATE_LIMIT_UNAVAILABLE") from None
        if count > limit:
            raise Problem(429, "RATE_LIMITED")

    def check_connection(self):
        if self.redis is None:
            raise Problem(503, "RATE_LIMIT_NOT_CONFIGURED")
        try:
            self.redis.ping()
        except RedisError:
            raise Problem(503, "RATE_LIMIT_UNAVAILABLE") from None


def encrypted_phone(settings, value):
    if value is None:
        return None
    try:
        key = settings.field_encrypt_key.get_secret_value()
        return Fernet(key.encode()).encrypt(value.encode()).decode()
    except (ValueError, TypeError):
        raise Problem(503, "PII_ENCRYPTION_NOT_CONFIGURED") from None
