import base64
import hashlib
import hmac
import json
import re
from datetime import timedelta

import jwt
from cryptography.fernet import Fernet

from app.account_deletion_store import utc
from app.errors import Problem


def key(settings, purpose):
    secret = settings.jwt_secret.get_secret_value().encode()
    if len(secret) < 32:
        raise Problem(503, "AUTH_NOT_CONFIGURED")
    return hmac.new(secret, ("nadree-account-deletion:" + purpose).encode(), hashlib.sha256).digest()


def seal(settings, value):
    return Fernet(base64.urlsafe_b64encode(key(settings, "private-data"))).encrypt(
        json.dumps(value, ensure_ascii=False).encode()).decode()


def unseal(settings, value):
    return json.loads(Fernet(base64.urlsafe_b64encode(key(settings, "private-data"))).decrypt(value.encode()))


def email_hash(settings, email):
    return hmac.new(key(settings, "email-lookup"), email.strip().casefold().encode(), hashlib.sha256).hexdigest()


def confirmation(settings, actor_id, snapshot_hash):
    at = utc()
    expires = at + timedelta(minutes=10)
    token = jwt.encode({"sub": actor_id, "scopeHash": snapshot_hash,
        "type": "account_deletion_confirmation", "iss": settings.jwt_issuer,
        "aud": "nadree-account-deletion", "iat": at, "exp": expires},
        key(settings, "confirmation"), algorithm="HS256")
    return token, expires


def verify_confirmation(settings, token, actor_id, snapshot_hash):
    try:
        value = jwt.decode(token, key(settings, "confirmation"), algorithms=["HS256"],
            issuer=settings.jwt_issuer, audience="nadree-account-deletion",
            options={"require": ["sub", "scopeHash", "type", "iat", "exp"]})
    except jwt.InvalidTokenError:
        raise Problem(422, "INVALID_CONFIRMATION", request_outcome={"requestAccepted": False}) from None
    if value["sub"] != actor_id or value["type"] != "account_deletion_confirmation":
        raise Problem(422, "INVALID_CONFIRMATION", request_outcome={"requestAccepted": False})
    if not hmac.compare_digest(value["scopeHash"], snapshot_hash):
        raise Problem(409, "DELETION_SCOPE_CHANGED", request_outcome={
            "requestAccepted": False, "nextAction": "RELOAD_AND_RECONFIRM"})


def validate_keys(idempotency, receipt):
    if not isinstance(idempotency, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", idempotency):
        raise Problem(422, "INVALID_DELETION_KEY", request_outcome={"requestAccepted": False})
    if not isinstance(receipt, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", receipt):
        raise Problem(422, "INVALID_DELETION_RECEIPT", request_outcome={"requestAccepted": False})
