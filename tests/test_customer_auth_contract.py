import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.errors import Problem
from app.firebase_auth import CustomerFirebaseAuth
from app.config import Settings


def settings(**values):
    values.setdefault("env", "test")
    return Settings(_env_file=None, jwt_secret="isolated-test-key-not-for-deployment-123456789", **values)


def test_customer_firebase_token_must_match_uid():
    verifier = CustomerFirebaseAuth(settings(), verify_fn=lambda token: {"uid": token, "auth_time": 1})

    assert verifier.verify_uid("uid-1", "uid-1")["uid"] == "uid-1"
    try:
        verifier.verify_uid("uid-1", "uid-2")
    except Problem as error:
        assert error.status == 401 and error.code == "FIREBASE_UID_MISMATCH"
    else:
        raise AssertionError("UID mismatch must be rejected")


def test_customer_firebase_token_is_required_when_verifier_is_configured():
    verifier = CustomerFirebaseAuth(settings(), verify_fn=lambda token: {"uid": "uid-1"})

    try:
        verifier.verify_uid("uid-1", None)
    except Problem as error:
        assert error.status == 401 and error.code == "FIREBASE_ID_TOKEN_REQUIRED"
    else:
        raise AssertionError("Missing Firebase ID token must be rejected")


def test_customer_firebase_auth_is_required_in_production_when_unconfigured():
    verifier = CustomerFirebaseAuth(settings(env="production"))

    try:
        verifier.verify_uid("uid-1", None)
    except Problem as error:
        assert error.status == 503 and error.code == "CUSTOMER_FIREBASE_AUTH_NOT_CONFIGURED"
    else:
        raise AssertionError("Production must not fall back to raw UID authentication")


@pytest.mark.parametrize("error", [None, "RevokedIdTokenError", "UserDisabledError", "UserNotFoundError"])
def test_sdk_verification_checks_revocation_and_rejects_invalid_accounts(monkeypatch, error):
    verify = Mock(return_value={"uid": "uid-1", "auth_time": 1})
    if error:
        verify.side_effect = type(error, (Exception,), {})("test rejection")
    monkeypatch.setitem(sys.modules, "firebase_admin", SimpleNamespace(auth=SimpleNamespace(verify_id_token=verify)))
    verifier = CustomerFirebaseAuth(settings(fcm_project_id="test-project", fcm_client_email="test@example.com",
                                            fcm_private_key="test-only-key"))
    monkeypatch.setattr(verifier, "_firebase_app", lambda: "test-app")
    if error:
        with pytest.raises(Problem) as exc:
            verifier.verify_uid("uid-1", "test-token")
        assert exc.value.status == 401
        assert exc.value.code == "FIREBASE_ID_TOKEN_INVALID"
    else:
        assert verifier.verify_uid("uid-1", "test-token")["auth_time"] == 1
    verify.assert_called_once_with("test-token", app="test-app", check_revoked=True)


@pytest.mark.parametrize("auth_time", [None, True, "123", -1])
def test_verified_token_requires_valid_authentication_time(auth_time):
    verifier = CustomerFirebaseAuth(settings(), verify_fn=lambda token: {"uid": "uid-1", "auth_time": auth_time})
    with pytest.raises(Problem) as exc:
        verifier.verify_uid("uid-1", "token")
    assert exc.value.code == "FIREBASE_ID_TOKEN_INVALID"
