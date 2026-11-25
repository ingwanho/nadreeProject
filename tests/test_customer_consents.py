"""Member consent timestamps share the existing signup/login and profile APIs."""
from datetime import timedelta

from cryptography.fernet import Fernet
from pydantic import SecretStr
import pytest
from sqlalchemy import func, select

from app.errors import Problem
from app.security import now
from test_nadri_auth import rental_tables

BASE = "/api/v1/nadree/user"


def member(ctx, uid):
    users = ctx["db"].table("MSP_RENTAL_USER")
    with ctx["engine"].connect() as connection:
        return dict(connection.execute(select(users).where(users.c.uid_token == uid)).mappings().one())


def sign_in(ctx, uid, **fields):
    response = ctx["client"].post(BASE + "/login", json={"UID": uid, **fields})
    assert response.status_code == 200, response.text
    return response.json(), {"Authorization": "Bearer " + response.json()["accessToken"]}


def test_signup_records_member_consents_and_login_retries_preserve_first_time(setup, monkeypatch):
    rental_tables(setup)
    at = now().replace(microsecond=123456)
    monkeypatch.setattr("app.rental_profile.now", lambda: at)
    data, headers = sign_in(setup, "member-first", privacyPolicyAgreed=True, termsAgreed=True)
    assert data["isNewUser"] is True
    expected = at.replace(microsecond=0).isoformat() + "Z"
    assert data["user"]["privacyPolicyAgreedAt"] == data["user"]["termsAgreedAt"] == expected
    before = member(setup, "member-first")
    at += timedelta(seconds=20)
    again, _ = sign_in(setup, "member-first", privacyPolicyAgreed=True, termsAgreed=True)
    assert again["isNewUser"] is False
    assert again["user"]["privacyPolicyAgreedAt"] == expected
    assert member(setup, "member-first") == before
    omitted, _ = sign_in(setup, "member-first")
    assert omitted["user"]["termsAgreedAt"] == expected
    viewed = setup["client"].get(BASE + "/profile", headers=headers)
    assert viewed.status_code == 200, viewed.text
    assert viewed.json()["user"]["privacyPolicyAgreedAt"] == expected


def test_profile_updates_consents_with_passport_and_license_and_supports_partial_acceptance(setup, monkeypatch):
    rental_tables(setup)
    setup["settings"].handover_encrypt_key = SecretStr(Fernet.generate_key().decode())
    at = now().replace(microsecond=345678)
    monkeypatch.setattr("app.rental_profile.now", lambda: at)
    data, headers = sign_in(setup, "member-profile")
    assert data["user"]["privacyPolicyAgreedAt"] is data["user"]["termsAgreedAt"] is None
    first = setup["client"].patch(BASE + "/profile", headers=headers, json={
        "passportNumber": "TEST-PASSPORT", "driverLicenseNumber": "TEST-LICENSE", "privacyPolicyAgreed": True})
    assert first.status_code == 200, first.text
    user = first.json()["user"]
    privacy_at = at.replace(microsecond=0).isoformat() + "Z"
    assert user["passportNumber"] == "TEST-PASSPORT" and user["driverLicenseNumber"] == "TEST-LICENSE"
    assert user["privacyPolicyAgreedAt"] == privacy_at and user["termsAgreedAt"] is None
    at += timedelta(seconds=7)
    second = setup["client"].patch(BASE + "/profile", headers=headers, json={"termsAgreed": True})
    assert second.status_code == 200, second.text
    assert second.json()["user"]["termsAgreedAt"] == at.replace(microsecond=0).isoformat() + "Z"
    assert second.json()["user"]["privacyPolicyAgreedAt"] == privacy_at
    before = member(setup, "member-profile")
    at += timedelta(seconds=7)
    retried = setup["client"].patch(BASE + "/profile", headers=headers,
        json={"privacyPolicyAgreed": True, "termsAgreed": True})
    assert retried.status_code == 200 and member(setup, "member-profile") == before
    renamed = setup["client"].patch(BASE + "/profile", headers=headers, json={"NAME": "Updated"})
    assert renamed.status_code == 200 and renamed.json()["user"]["privacyPolicyAgreedAt"] == privacy_at


@pytest.mark.parametrize("path", ["login", "profile"])
@pytest.mark.parametrize("fields", [{"privacyPolicyAgreed": False}, {"termsAgreed": None},
    {"privacyPolicyAgreed": "true"}, {"termsAgreed": 1},
    {"privacyPolicyAgreed": True, "termsAgreed": False}, {"termsAgreedAt": "2020-01-01T00:00:00Z"}])
def test_invalid_member_consents_do_not_register_or_update(setup, path, fields):
    tables = rental_tables(setup)
    uid = "member-invalid"
    if path == "login":
        response = setup["client"].post(BASE + "/login", json={"UID": uid, **fields})
        with setup["engine"].connect() as connection:
            assert connection.scalar(select(func.count()).select_from(tables["MSP_RENTAL_USER"])) == 0
    else:
        _, headers = sign_in(setup, uid)
        before = member(setup, uid)
        response = setup["client"].patch(BASE + "/profile", headers=headers, json=fields)
        assert member(setup, uid) == before
    assert response.status_code == 422 and response.json()["errorCode"] == "INVALID_INPUT"


def test_profile_auth_and_uid_cannot_be_used_to_record_other_members_consents(setup, signin):
    rental_tables(setup)
    _, headers = sign_in(setup, "member-owner")
    sign_in(setup, "member-other")
    body = {"privacyPolicyAgreed": True}
    assert setup["client"].patch(BASE + "/profile", json=body).status_code == 401
    assert setup["client"].patch(BASE + "/profile", headers=signin(), json=body).status_code == 401
    assert setup["client"].patch(BASE + "/profile", headers=headers,
        json={**body, "UID": "member-other"}).status_code == 422
    assert member(setup, "member-other")["privacy_policy_agreed_at"] is None


def test_failed_firebase_auth_does_not_record_or_register_consents(setup, monkeypatch):
    tables = rental_tables(setup)
    def rejected(*args):
        raise Problem(401, "INVALID_FIREBASE_TOKEN")
    monkeypatch.setattr(setup["app"].state.customer_auth, "verify_uid", rejected)
    response = setup["client"].post(BASE + "/login", json={"UID": "member-auth-failed", "privacyPolicyAgreed": True})
    assert response.status_code == 401
    with setup["engine"].connect() as connection:
        assert connection.scalar(select(func.count()).select_from(tables["MSP_RENTAL_USER"])) == 0


def test_account_deletion_clears_member_consent_and_rejoining_does_not_restore_it(setup, monkeypatch):
    rental_tables(setup)
    at = now()
    monkeypatch.setattr("app.customer_rentals.now", lambda: at)
    monkeypatch.setattr("app.rental_profile.now", lambda: at)
    monkeypatch.setattr(setup["app"].state.customer_auth, "delete_uid", lambda uid: None)
    _, headers = sign_in(setup, "member-rejoin", privacyPolicyAgreed=True, termsAgreed=True)
    assert setup["client"].delete(BASE + "/account", headers=headers).status_code == 200
    deleted = member(setup, "member-rejoin")
    assert deleted["privacy_policy_agreed_at"] is deleted["terms_agreed_at"] is None
    at += timedelta(seconds=3)
    data, fresh_headers = sign_in(setup, "member-rejoin")
    assert data["user"]["privacyPolicyAgreedAt"] is data["user"]["termsAgreedAt"] is None
    accepted = setup["client"].patch(BASE + "/profile", headers=fresh_headers, json={"privacyPolicyAgreed": True})
    assert accepted.status_code == 200
    assert accepted.json()["user"]["privacyPolicyAgreedAt"] == at.replace(microsecond=0).isoformat() + "Z"


def test_handover_consent_api_and_fields_are_removed(setup):
    schema = setup["client"].get("/openapi.json").json()
    old_path = "/api/v1/nadree/rental/handovers/{handover_id}/consents"
    assert old_path not in schema["paths"]
    assert "HandoverConsents" not in schema["components"]["schemas"]
    assert "privacyPolicyAgreedAt" not in schema["components"]["schemas"]["HandoverItem"]["properties"]
    response = setup["client"].post(old_path.replace("{handover_id}", "retired-id"), json={"termsAgreed": True})
    assert response.status_code == 404
