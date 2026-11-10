"""Signup permits ten attempts while account and invitation checks remain active."""
from collections import Counter

import pytest
from sqlalchemy import func, select

from app.errors import Problem


def counts(setup):
    with setup["engine"].connect() as connection:
        return {name: connection.scalar(select(func.count()).select_from(setup["db"].table(name)))
                for name in ("MSP_ADMIN", "MSP_RENTAL_ADMIN_REQUEST")}


@pytest.mark.parametrize("window,seconds", [("ip", 300), ("subject", 3600)])
def test_ten_attempts_reach_invite_validation_and_eleventh_is_limited(client, setup, monkeypatch, window, seconds):
    before = counts(setup)
    calls = Counter()
    configured = {}

    def limited(key, limit=10, seconds=60):
        calls[key] += 1
        configured[key] = (limit, seconds)
        # Isolate each window; the other window is covered by its own case.
        if key.startswith("admin-signup:" + window + ":") and calls[key] > limit:
            raise Problem(429, "RATE_LIMITED")

    monkeypatch.setattr(setup["limiter"], "check", limited)
    body = {"loginId": "limited-invalid-invite", "email": "invalid-invite@example.com",
            "name": "Test applicant", "password": "Test-password-123!", "inviteCode": "missing-invite"}

    for _ in range(10):
        response = client.post("/nadreego/admin/signup", json=body)
        assert response.status_code == 404
        assert response.json()["errorCode"] == "INVITE_CODE_NOT_FOUND"

    rejected = client.post("/nadreego/admin/signup", json=body)
    assert rejected.status_code == 429 and rejected.json()["errorCode"] == "RATE_LIMITED"
    target = next(key for key in calls if key.startswith("admin-signup:" + window + ":"))
    assert calls[target] == 11 and configured[target] == (10, seconds)
    assert configured["admin-signup:ip:testclient"] == (10, 300)
    assert configured["admin-signup:subject:invalid-invite@example.com"] == (10, 3600)
    assert counts(setup) == before


def test_ten_signup_attempts_preserve_duplicate_checks_before_rate_limit(client, setup, monkeypatch):
    before = counts(setup)
    calls = Counter()

    def limited(key, limit=10, seconds=60):
        calls[key] += 1
        if calls[key] > limit:
            raise Problem(429, "RATE_LIMITED")

    monkeypatch.setattr(setup["limiter"], "check", limited)
    body = {"loginId": "limited-pending-manager", "email": "limited-manager@example.com",
            "name": "Test applicant", "password": "Test-password-123!",
            "representativeEmail": "primary@example.com"}

    created = client.post("/nadreego/admin/signup", json=body)

    assert created.status_code == 201, created.text
    assert created.json()["accountStatus"] == "PENDING_APPROVAL"
    assert created.json()["requestStatus"] == "REQUESTED"
    for _ in range(9):
        duplicate = client.post("/nadreego/admin/signup", json=body)
        assert duplicate.status_code == 409
        assert duplicate.json()["errorCode"] == "ADMIN_REQUEST_ALREADY_EXISTS"
    assert calls["admin-signup:ip:testclient"] == 10
    assert calls["admin-signup:subject:limited-manager@example.com"] == 10
    assert counts(setup) == {name: value + 1 for name, value in before.items()}

    blocked = client.post("/nadreego/admin/signup", json=body)
    assert blocked.status_code == 429 and blocked.json()["errorCode"] == "RATE_LIMITED"
    assert counts(setup) == {name: value + 1 for name, value in before.items()}
