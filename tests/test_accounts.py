from datetime import timedelta

import jwt
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select, update

from app.security import GENERAL, SESSION_MARKER, fingerprint, now


def admin_row(setup, ident="primary"):
    table = setup["db"].table("MSP_ADMIN")
    with setup["engine"].connect() as conn:
        return conn.execute(select(table).where(table.c.admin_id == ident)).mappings().one()


def test_login_response_and_hash_storage(client, signin, setup):
    headers = signin(fcmToken="device-1")
    claims = jwt.decode(headers["Authorization"][7:], setup["settings"].jwt_secret.get_secret_value(),
                        algorithms=["HS256"], audience="nadreego", issuer="nadree-api")
    table = setup["db"].table("MSP_REFRESH_TOKEN")
    with setup["engine"].connect() as conn:
        row = conn.execute(select(table)).mappings().one()
    assert claims["sid"] == row["token_id"]
    assert row["token_hash"] == fingerprint(headers["X-Refresh-Token"])
    assert row["user_agent"] == SESSION_MARKER
    assert admin_row(setup)["fcm_token"] == "device-1"
    assert len(setup["limiter"].calls) == 2


@pytest.mark.parametrize("body", [
    {"email": "missing@example.com", "password": "Test-password-123!"},
    {"email": "primary@example.com", "password": "incorrect"},
    {"email": "primary@example.com", "password": "x" * 73},
])
def test_invalid_login_is_generic(client, body):
    result = client.post("/nadreego/admin/login", json=body)
    assert result.status_code == 401
    assert result.json() == {"status": "fail", "errorCode": "INVALID_CREDENTIALS"}


@pytest.mark.parametrize("values,code", [({"mfa_method": "email"}, "MFA_REQUIRED"),
                                         ({"is_active": 0}, "INVALID_CREDENTIALS")])
def test_account_policy_not_bypassed(client, setup, values, code):
    table = setup["db"].table("MSP_ADMIN")
    with setup["engine"].begin() as conn:
        conn.execute(update(table).where(table.c.admin_id == "primary").values(**values))
    result = client.post("/nadreego/admin/login", json={"email": "primary@example.com", "password": "Test-password-123!"})
    assert result.json()["errorCode"] == code


def test_ambiguous_email_never_selects_arbitrary_account(client, setup):
    table = setup["db"].table("MSP_ADMIN")
    with setup["engine"].begin() as conn:
        conn.execute(update(table).where(table.c.admin_id == "general").values(email="primary@example.com"))
    result = client.post("/nadreego/admin/login", json={"email": "primary@example.com", "password": "Test-password-123!"})
    assert result.status_code == 401


def test_refresh_rotates_and_rejects_previous_token(client, signin):
    old = signin()
    result = client.get("/nadreego/admin/refresh", headers={"X-Refresh-Token": old["X-Refresh-Token"]})
    assert result.status_code == 200
    assert result.json()["refreshToken"] != old["X-Refresh-Token"]
    assert client.get("/nadreego/admin/refresh", headers=old).status_code == 401
    assert client.get("/nadreego/admin/refresh", headers={"X-Refresh-Token": result.json()["refreshToken"]}).status_code == 200


def test_admin_refresh_sessions_are_capped_at_three(client, signin, setup):
    first = signin()
    table = setup["db"].table("MSP_REFRESH_TOKEN")
    with setup["engine"].begin() as conn:
        conn.execute(update(table).where(table.c.token_hash == fingerprint(first["X-Refresh-Token"])).values(
            issued_at=now() - timedelta(days=1)))
    second, third, fourth = signin(), signin(), signin()
    with setup["engine"].connect() as conn:
        rows = conn.execute(select(table).where(table.c.admin_id == "primary",
            table.c.user_agent == SESSION_MARKER)).mappings().all()
    active = [row for row in rows if row["revoked_at"] is None]
    assert len(active) == 3
    old = next(row for row in rows if row["token_hash"] == fingerprint(first["X-Refresh-Token"]))
    assert old["revoked_at"] is not None
    assert client.get("/nadreego/admin/refresh", headers=first).status_code == 401
    assert client.get("/nadreego/admin/refresh", headers=fourth).status_code == 200


def test_expired_refresh_and_revoked_access(client, signin, setup):
    headers = signin()
    table = setup["db"].table("MSP_REFRESH_TOKEN")
    with setup["engine"].begin() as conn:
        conn.execute(update(table).values(expires_at=now() - timedelta(seconds=1)))
    assert client.get("/nadreego/admin/refresh", headers=headers).status_code == 401
    assert client.post("/nadreego/admin/fcmToken", headers=headers, json={"fcmToken": "x"}).status_code == 401


@pytest.mark.parametrize("change", [{"iss": "old-service"}, {"aud": "old-web"}, {"type": "refresh"}, {"exp": 1}])
def test_access_claims_are_checked(client, signin, setup, change):
    headers = signin()
    secret = setup["settings"].jwt_secret.get_secret_value()
    claims = jwt.decode(headers["Authorization"][7:], secret, algorithms=["HS256"], audience="nadreego")
    claims.update(change)
    headers["Authorization"] = "Bearer " + jwt.encode(claims, secret, algorithm="HS256")
    assert client.post("/nadreego/admin/fcmToken", headers=headers, json={"fcmToken": "x"}).status_code == 401


def test_logout_old_device_preserves_latest_fcm(client, signin, setup):
    old = signin(fcmToken="old-device")
    latest = signin(fcmToken="latest-device")
    assert client.get("/nadreego/admin/logout", headers={**old, "X-FCM-Token": "old-device"}).status_code == 200
    assert admin_row(setup)["fcm_token"] == "latest-device"
    assert client.post("/nadreego/admin/fcmToken", headers=old, json={"fcmToken": "x"}).status_code == 401
    assert client.get("/nadreego/admin/logout", headers={**latest, "X-FCM-Token": "latest-device"}).status_code == 200
    assert admin_row(setup)["fcm_token"] == "latest-device"


def test_logout_without_fcm_and_token_pair_mismatch(client, signin, setup):
    first, second = signin(fcmToken="preserved"), signin("general")
    result = client.get("/nadreego/admin/logout", headers={**first, "X-Refresh-Token": second["X-Refresh-Token"]})
    assert result.json()["errorCode"] == "TOKEN_PAIR_MISMATCH"
    assert client.get("/nadreego/admin/logout", headers=first).status_code == 200
    assert admin_row(setup)["fcm_token"] == "preserved"


def test_fcm_updates_only_caller_and_does_not_leak_validation_input(client, signin, setup):
    headers = signin("general")
    assert client.post("/nadreego/admin/fcmToken", headers=headers, json={"fcmToken": "new"}).json() == {"status": "success"}
    assert admin_row(setup, "general")["fcm_token"] == "new"
    assert admin_row(setup)["fcm_token"] is None
    result = client.post("/nadreego/admin/fcmToken", headers=headers, json={"fcmToken": "private-token", "adminId": "primary"})
    assert result.status_code == 422 and "private-token" not in result.text


def test_revoke_role_takes_effect_without_waiting_for_jwt_expiration(client, signin, setup):
    headers = signin("general")
    table = setup["db"].table("MSP_ADMIN_ROLE")
    with setup["engine"].begin() as conn:
        conn.execute(delete(table).where(table.c.admin_id == "general", table.c.role_code == GENERAL))
    assert client.post("/nadreego/admin/fcmToken", headers=headers, json={"fcmToken": "x"}).status_code == 403


def test_profile_name_and_sensitive_reauthentication(client, signin, setup):
    headers = signin()
    result = client.post("/nadreego/admin/update", headers=headers, json={"name": "Updated"})
    assert result.json()["name"] == "Updated"
    assert admin_row(setup)["admin_name"] == "Updated"
    assert client.post("/nadreego/admin/update", headers={"Authorization": headers["Authorization"]},
                       json={"password": "Changed-password-123!"}).status_code == 401
    assert client.post("/nadreego/admin/update", headers=headers, json={"password": "Changed-password-123!"}).status_code == 200
    assert client.post("/nadreego/admin/fcmToken", headers=headers, json={"fcmToken": "x"}).status_code == 401
    assert client.post("/nadreego/admin/login", json={"email": "primary@example.com", "password": "Changed-password-123!"}).status_code == 200


def test_email_update_validation_conflict_and_session_invalidation(client, signin):
    headers = signin()
    assert client.post("/nadreego/admin/update", headers=headers, json={"email": "invalid"}).status_code == 422
    assert client.post("/nadreego/admin/update", headers=headers, json={"email": "general@example.com"}).status_code == 409
    result = client.post("/nadreego/admin/update", headers=headers, json={"email": "new@example.com"})
    assert result.status_code == 200 and result.json()["email"] == "new@example.com"
    assert client.get("/nadreego/admin/refresh", headers=headers).status_code == 401


def test_old_login_cannot_change_password_even_after_refresh(client, signin, setup):
    headers = signin()
    table = setup["db"].table("MSP_REFRESH_TOKEN")
    with setup["engine"].begin() as conn:
        conn.execute(update(table).values(issued_at=now() - timedelta(minutes=6)))
    fresh = client.get("/nadreego/admin/refresh", headers=headers).json()
    result = client.post("/nadreego/admin/update", headers={"Authorization": "Bearer " + fresh["accessToken"],
        "X-Refresh-Token": fresh["refreshToken"]}, json={"password": "New-password-123!"})
    assert result.json()["errorCode"] == "REAUTHENTICATION_REQUIRED"


@pytest.mark.parametrize("body", [{}, {"name": None}, {"password": "short"}, {"email": None}])
def test_invalid_profile_has_no_changes(client, signin, setup, body):
    assert client.post("/nadreego/admin/update", headers=signin(), json=body).status_code == 422
    assert admin_row(setup)["admin_name"] == "primary"


def test_phone_does_not_fall_back_to_plaintext_or_truncate(client, signin, setup):
    headers = signin()
    result = client.post("/nadreego/admin/update", headers=headers, json={"phone": "01012345678"})
    assert result.json()["errorCode"] == "PII_ENCRYPTION_NOT_CONFIGURED"
    from pydantic import SecretStr
    setup["settings"].field_encrypt_key = SecretStr(Fernet.generate_key().decode())
    result = client.post("/nadreego/admin/update", headers=headers, json={"phone": "01012345678"})
    assert result.status_code == 200
    stored = admin_row(setup)["phone"]
    assert stored != "01012345678" and len(stored) <= 200
    assert Fernet(setup["settings"].field_encrypt_key.get_secret_value().encode()).decrypt(stored.encode()) == b"01012345678"
    # An old schema still fails closed; it never truncates or stores plaintext.
    setup["db"].table("MSP_ADMIN").c.phone.type.length = 20
    result = client.post("/nadreego/admin/update", headers=headers, json={"phone": "01099999999", "name": "Must not change"})
    assert result.json()["errorCode"] == "PHONE_STORAGE_MAPPING_REQUIRED"
    assert admin_row(setup)["phone"] == stored and admin_row(setup)["admin_name"] == "primary"


@pytest.mark.parametrize("phone", ["+82 10-1234-5678", "1" * 20])
def test_phone_input_limits_and_encryption_storage(client, signin, setup, phone):
    from pydantic import SecretStr
    setup["settings"].field_encrypt_key = SecretStr(Fernet.generate_key().decode())
    assert client.post("/nadreego/admin/update", headers=signin(), json={"phone": phone}).status_code == 200
    stored = admin_row(setup)["phone"]
    assert len(stored) <= 200
    assert Fernet(setup["settings"].field_encrypt_key.get_secret_value().encode()).decrypt(stored.encode()).decode() == phone


def test_phone_ciphertext_over_200_is_rejected_without_truncation(client, signin, setup):
    from pydantic import SecretStr
    setup["settings"].field_encrypt_key = SecretStr(Fernet.generate_key().decode())
    response = client.post("/nadreego/admin/update", headers=signin(), json={"phone": "\U0001f600" * 20})
    assert response.status_code == 503 and response.json()["errorCode"] == "PHONE_STORAGE_MAPPING_REQUIRED"
    assert admin_row(setup)["phone"] is None


def test_spot_code_is_an_invite_not_a_membership_grant(client, signin, setup):
    headers = signin()
    assert client.post("/nadreego/admin/spotcheck", headers=headers, json={"spotCode": "CT1-ORG01"}).status_code == 404
    result = client.post("/nadreego/admin/spotcheck", headers=headers, json={"spotCode": "invite-child"})
    assert result.status_code == 200 and result.json()["spotMasterId"] == "child"
    assert admin_row(setup)["primary_spot_master_id"] == "root"


def test_unconfigured_password_reset_does_not_mutate_credentials(client, setup):
    before = admin_row(setup)["password_hash"]
    response = client.post("/nadreego/admin/findpswd", json={"email": "primary@example.com"})
    assert response.status_code == 503
    assert response.json()["errorCode"] == "MAIL_NOT_CONFIGURED"
    assert admin_row(setup)["password_hash"] == before


def test_password_reset_email_and_session_revocation(client, signin, setup):
    class Mailbox:
        def check_configuration(self):
            pass

        def send(self, recipient, password):
            self.recipient, self.password = recipient, password

    mailbox = Mailbox()
    setup["app"].state.mailer = mailbox
    headers = signin()
    response = client.post("/nadreego/admin/findpswd", json={"email": "primary@example.com"})
    assert response.json() == {"status": "success"}
    assert mailbox.recipient == "primary@example.com"
    assert mailbox.password not in response.text
    assert client.get("/nadreego/admin/refresh", headers=headers).status_code == 401
    assert client.post("/nadreego/admin/login", json={"email": mailbox.recipient, "password": mailbox.password}).status_code == 200
    assert client.post("/nadreego/admin/findpswd", json={"email": "unknown@example.com"}).json() == response.json()


def test_password_reset_mail_failure_rolls_back(client, signin, setup):
    from app.errors import Problem

    class FailedMailbox:
        def check_configuration(self):
            pass

        def send(self, recipient, password):
            raise Problem(503, "MAIL_UNAVAILABLE")

    setup["app"].state.mailer = FailedMailbox()
    headers = signin()
    before = admin_row(setup)["password_hash"]
    response = client.post("/nadreego/admin/findpswd", json={"email": "primary@example.com"})
    assert response.status_code == 503
    assert admin_row(setup)["password_hash"] == before
    assert client.get("/nadreego/admin/refresh", headers=headers).status_code == 200
