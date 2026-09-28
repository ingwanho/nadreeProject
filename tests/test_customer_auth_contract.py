from app.errors import Problem
from app.firebase_auth import CustomerFirebaseAuth
from app.config import Settings


def settings(**values):
    values.setdefault("env", "test")
    return Settings(_env_file=None, jwt_secret="isolated-test-key-not-for-deployment-123456789", **values)


def test_customer_firebase_token_must_match_uid():
    verifier = CustomerFirebaseAuth(settings(), verify_fn=lambda token: {"uid": token})

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
