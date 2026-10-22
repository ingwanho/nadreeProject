"""FCM registration must preserve same-token chat sessions and queued pushes."""
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.errors import Problem
from app.fcm import FcmSender
from app.rental_schema import metadata
from app.security import now


def registration(setup, signin, route):
    token = "opaque-current-test-token"
    if route == "customer":
        metadata.create_all(setup["engine"])
        login = setup["client"].post("/api/v1/nadree/user/login", json={"UID": "chat-fcm-user", "fcmToken": token})
        assert login.status_code == 200
        result = login.json()
        headers = {"Authorization": "Bearer " + result["accessToken"], "X-Refresh-Token": result["refreshToken"]}
        table_name, key, ident, sessions = "MSP_RENTAL_USER", "uid_token", "chat-fcm-user", "MSP_RENTAL_USER_REFRESH_TOKEN"
        method, path = "PATCH", "/api/v1/nadree/user/profile"
    else:
        headers = signin(fcmToken=token)
        table_name, key, ident, sessions = "MSP_ADMIN", "admin_id", "primary", "MSP_REFRESH_TOKEN"
        method = "POST"
        path = "/nadreego/admin/fcmToken" if route == "admin_token" else "/nadreego/admin/update"
    table = setup["db"].table(table_name)
    tokens = setup["db"].table(sessions)
    original_stamp = now() - timedelta(hours=1)
    with setup["engine"].begin() as conn:
        conn.execute(update(table).where(table.c[key] == ident).values(fcm_token_updated_at=original_stamp))
        session_id = conn.scalar(select(tokens.c.token_id).where(tokens.c[key] == ident, tokens.c.revoked_at.is_(None)))
    queued = {"table": table_name, "key_column": key, "event": "CHAT_MESSAGE",
              "recipients": [{"id": ident, "token": token, "updated_at": original_stamp, "chat_session_id": session_id}]}
    return method, path, headers, table, key, ident, original_stamp, queued


@pytest.mark.parametrize("route", ["customer", "admin_token", "admin_profile"])
def test_same_fcm_registration_preserves_chat_and_already_queued_push(setup, signin, monkeypatch, route):
    method, path, headers, table, key, ident, stamp, queued = registration(setup, signin, route)
    def forbidden(uid):
        pytest.fail("Unchanged FCM registration must not revoke chat")
    monkeypatch.setattr(setup["app"].state.chat, "revoke", forbidden)
    for _ in range(2):
        result = setup["client"].request(method, path, headers=headers, json={"fcmToken": "opaque-current-test-token"})
        assert result.status_code == 200
    with setup["engine"].connect() as conn:
        row = conn.execute(select(table).where(table.c[key] == ident)).mappings().one()
    assert row["fcm_token"] == "opaque-current-test-token" and row["fcm_token_updated_at"] == stamp
    assert FcmSender._current_recipients(setup["db"], queued)["recipients"] == queued["recipients"]


@pytest.mark.parametrize("route", ["customer", "admin_token", "admin_profile"])
def test_changed_fcm_registration_revokes_chat_and_filters_old_push(setup, signin, monkeypatch, route):
    method, path, headers, table, key, ident, stamp, queued = registration(setup, signin, route)
    calls = []
    monkeypatch.setattr(setup["app"].state.chat, "revoke", lambda uid: calls.append(uid))
    result = setup["client"].request(method, path, headers=headers, json={"fcmToken": "opaque-new-test-token"})
    assert result.status_code == 200 and len(calls) == 1
    with setup["engine"].connect() as conn:
        row = conn.execute(select(table).where(table.c[key] == ident)).mappings().one()
    assert row["fcm_token"] == "opaque-new-test-token" and row["fcm_token_updated_at"] != stamp
    assert FcmSender._current_recipients(setup["db"], queued)["recipients"] == []


@pytest.mark.parametrize("route", ["customer", "admin_token", "admin_profile"])
def test_changed_fcm_registration_rolls_back_if_chat_cannot_be_revoked(setup, signin, monkeypatch, route):
    method, path, headers, table, key, ident, stamp, queued = registration(setup, signin, route)
    def unavailable(uid):
        raise Problem(503, "TEST_CHAT_SYNC_FAILED")
    monkeypatch.setattr(setup["app"].state.chat, "revoke", unavailable)
    result = setup["client"].request(method, path, headers=headers, json={"fcmToken": "opaque-new-test-token"})
    assert result.status_code == 503
    with setup["engine"].connect() as conn:
        row = conn.execute(select(table).where(table.c[key] == ident)).mappings().one()
    assert row["fcm_token"] == "opaque-current-test-token" and row["fcm_token_updated_at"] == stamp
    assert FcmSender._current_recipients(setup["db"], queued)["recipients"] == queued["recipients"]


@pytest.mark.parametrize("field,value", [("password", "Updated-test-password-123!"), ("email", "changed@example.com")])
def test_unchanged_fcm_does_not_bypass_sensitive_admin_session_revocation(setup, signin, monkeypatch, field, value):
    method, path, headers, _, _, _, _, _ = registration(setup, signin, "admin_profile")
    calls = []
    monkeypatch.setattr(setup["app"].state.chat, "revoke", lambda uid: calls.append(uid))
    result = setup["client"].request(method, path, headers=headers,
                                      json={"fcmToken": "opaque-current-test-token", field: value})
    assert result.status_code == 200 and len(calls) == 1
    assert setup["client"].get("/nadreego/admin/refresh", headers=headers).status_code == 401


def test_customer_profile_fields_still_update_with_same_fcm(setup, signin, monkeypatch):
    method, path, headers, table, key, ident, stamp, _ = registration(setup, signin, "customer")
    def forbidden(uid):
        pytest.fail("Unchanged FCM must preserve chat while editing profile")
    monkeypatch.setattr(setup["app"].state.chat, "revoke", forbidden)
    result = setup["client"].request(method, path, headers=headers,
                                      json={"fcmToken": "opaque-current-test-token", "NAME": "Updated customer"})
    assert result.status_code == 200 and result.json()["user"]["name"] == "Updated customer"
    with setup["engine"].connect() as conn:
        row = conn.execute(select(table).where(table.c[key] == ident)).mappings().one()
    assert row["fcm_token_updated_at"] == stamp


def test_admin_profile_fields_still_update_with_same_fcm(setup, signin, monkeypatch):
    method, path, headers, table, key, ident, stamp, _ = registration(setup, signin, "admin_profile")
    def forbidden(uid):
        pytest.fail("Unchanged FCM must preserve chat while editing profile")
    monkeypatch.setattr(setup["app"].state.chat, "revoke", forbidden)
    result = setup["client"].request(method, path, headers=headers,
                                      json={"fcmToken": "opaque-current-test-token", "name": "Updated admin"})
    assert result.status_code == 200 and result.json()["name"] == "Updated admin"
    with setup["engine"].connect() as conn:
        row = conn.execute(select(table).where(table.c[key] == ident)).mappings().one()
    assert row["fcm_token_updated_at"] == stamp
