"""Personal form fields shared by customer profiles and rental handovers."""
import json
from typing import Annotated

from cryptography.fernet import Fernet, InvalidToken
from pydantic import Field
from sqlalchemy import select, update

from app.db import require_columns
from app.errors import Problem
from app.security import encrypted_phone, now

DocumentNumber = Annotated[str, Field(strict=True, min_length=1, max_length=100, pattern=r"\S")]
SnsInfo = dict[Annotated[str, Field(min_length=1, max_length=50)],
               Annotated[str, Field(strict=True, max_length=500)]]
NUMBER_FIELDS = {"passportNumber": "passport_number_enc", "driverLicenseNumber": "driver_license_number_enc"}


def decrypt(settings, value):
    if value is None:
        return None
    try:
        return Fernet(settings.field_encrypt_key.get_secret_value().encode()).decrypt(value.encode()).decode()
    except (ValueError, TypeError):
        raise Problem(503, "PII_ENCRYPTION_NOT_CONFIGURED") from None
    except (InvalidToken, UnicodeError):
        raise Problem(503, "PII_DECRYPTION_FAILED") from None


def encode_sns(value):
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode()) > 8192:
        raise Problem(422, "INVALID_INPUT")
    return encoded


def read_sns(value):
    if value is None:
        return None
    try:
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise Problem(503, "PROFILE_STORAGE_INVALID") from None


def personal_view(settings, user):
    return {**{key: decrypt(settings, user.get(column)) for key, column in NUMBER_FIELDS.items()},
            "snsInfo": read_sns(user.get("sns_info"))}


def sync_personal(request, session, uid, fields):
    """Only explicitly supplied fields are updated; caller owns the transaction."""
    values = {column: encrypted_phone(request.app.state.settings, fields[key])
              for key, column in NUMBER_FIELDS.items() if key in fields}
    if "snsInfo" in fields:
        values["sns_info"] = encode_sns(fields["snsInfo"])
    if not values:
        return
    users = request.app.state.db.table("MSP_RENTAL_USER")
    if not session.execute(select(users.c.uid_token).where(users.c.uid_token == uid).with_for_update()).first():
        raise Problem(404, "RENTAL_USER_NOT_FOUND")
    require_columns(users, values)
    session.execute(update(users).where(users.c.uid_token == uid).values(**values, updated_at=now()))
