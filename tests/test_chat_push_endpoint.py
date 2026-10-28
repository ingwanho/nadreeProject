"""Service-identity, replay and HTTP/worker concurrency checks without external calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Event
from types import SimpleNamespace

import pytest
from google.auth.exceptions import TransportError

from app import chat_push_endpoint
from app.chat_push import event_lock
from test_chat_push_recovery import env

EVENT_ID = "a" * 64
AUDIENCE = "https://backend.example/internal/chat/push-events"
HEADERS = {"Authorization": "Bearer synthetic-service-token"}


@pytest.fixture
def endpoint(env, monkeypatch):
    settings = env.app.state.settings
    settings.fcm_chat_enabled = True
    settings.chat_push_audience = AUDIENCE
    settings.chat_push_invoker_email = "trigger@isolated.iam.gserviceaccount.com"
    settings.chat_push_invoker_subject = "123456789012345678901"
    env.app.state.chat, env.app.state.fcm = env.chat, env.sender
    env.store.docs["chatPushEvents/" + EVENT_ID] = env.store.docs.pop("chatPushEvents/event")
    env.claims = {"email": settings.chat_push_invoker_email, "sub": settings.chat_push_invoker_subject,
                  "email_verified": True}
    def verify(token, request, *, audience):
        assert token == "synthetic-service-token" and audience == AUDIENCE
        return env.claims
    monkeypatch.setattr(chat_push_endpoint.id_token, "verify_oauth2_token", verify)
    env.post = lambda **kwargs: env.client.post("/internal/chat/push-events", headers=HEADERS,
                                               json={"eventId": EVENT_ID}, **kwargs)
    return env


def test_authenticated_callback_and_replay_send_once(endpoint):
    first, replay = endpoint.post(), endpoint.post()
    assert first.status_code == replay.status_code == 200
    assert first.json() == {"status": "success", "processing": "completed"}
    assert len(endpoint.calls) == 1
    assert "/internal/chat/push-events" not in endpoint.client.get("/openapi.json").json()["paths"]


def test_callback_failure_is_recovered_by_the_periodic_worker(endpoint):
    endpoint.outcomes.append({"retryable": ["primary"]})
    result = endpoint.post()
    assert result.status_code == 200 and result.json()["processing"] == "pending"
    assert endpoint.post().json()["processing"] == "pending" and len(endpoint.calls) == 1
    endpoint.clock.at += timedelta(seconds=30)
    assert endpoint.tick()["accepted"] == 1
    assert len(endpoint.calls) == 2 and endpoint.post().json()["processing"] == "completed"


def test_callback_error_after_sql_commit_remains_recoverable(endpoint):
    endpoint.store.failure = lambda value: set(value) == {"inboxSynced"}
    response = endpoint.post()
    assert response.status_code == 503 and response.json()["errorCode"] == "CHAT_PUSH_PROCESSING_DEFERRED"
    assert endpoint.tick()["accepted"] == 1 and len(endpoint.calls) == 1


@pytest.mark.parametrize("header", [None, "Basic synthetic", "Bearer", "Bearer one two"])
def test_missing_or_malformed_service_credentials_are_rejected(endpoint, header):
    headers = {"Authorization": header} if header else {}
    response = endpoint.client.post("/internal/chat/push-events", headers=headers, json={"eventId": EVENT_ID})
    assert response.status_code == 401 and not endpoint.calls


@pytest.mark.parametrize("field,value", [("email", "other@isolated.iam.gserviceaccount.com"),
                                        ("sub", "unapproved-subject"), ("email_verified", False), ("email_verified", "true")])
def test_other_google_identities_cannot_dispatch(endpoint, field, value):
    endpoint.claims[field] = value
    response = endpoint.post()
    assert response.status_code == 403 and not endpoint.calls


@pytest.mark.parametrize("error,status", [(ValueError("invalid token"), 401), (TransportError("certificate unavailable"), 503)])
def test_token_verification_failure_is_fail_closed(endpoint, monkeypatch, error, status):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(chat_push_endpoint.id_token, "verify_oauth2_token", fail)
    response = endpoint.post()
    assert response.status_code == status and not endpoint.calls
    assert "synthetic-service-token" not in response.text


@pytest.mark.parametrize("field", ["chat_push_audience", "chat_push_invoker_email", "chat_push_invoker_subject"])
def test_incomplete_configuration_is_fail_closed(endpoint, field):
    setattr(endpoint.app.state.settings, field, "")
    assert endpoint.post().status_code == 503 and not endpoint.calls


@pytest.mark.parametrize("body", [{"eventId": "not-an-event"}, {"eventId": "A"*64},
                                {"eventId": EVENT_ID, "fcmToken": "forged"}, {"eventId": EVENT_ID, "shopId": "foreign"}])
def test_callback_cannot_supply_recipients_or_scope(endpoint, body):
    result = endpoint.client.post("/internal/chat/push-events", headers=HEADERS, json=body)
    assert result.status_code == 422 and not endpoint.calls


def test_missing_event_is_terminal_and_has_no_side_effects(endpoint):
    endpoint.store.docs.pop("chatPushEvents/"+EVENT_ID)
    assert endpoint.post().json()["processing"] == "missing" and not endpoint.calls


def test_old_completed_event_is_not_replayed(endpoint):
    document = endpoint.store.docs["chatPushEvents/"+EVENT_ID]
    document["inboxSynced"] = True
    before = deepcopy(document)
    assert endpoint.post().json()["processing"] == "completed"
    assert document == before and not endpoint.calls


@pytest.mark.parametrize("first_path", ["http", "worker"])
def test_http_and_worker_cannot_deliver_same_event_concurrently(endpoint, monkeypatch, first_path):
    entered, release = Event(), Event()
    original = endpoint.sender._send
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(endpoint.sender, "_send", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(endpoint.post if first_path == "http" else endpoint.tick)
        try:
            assert entered.wait(10)
            second = endpoint.post()
            assert second.status_code == 503 and second.json()["errorCode"] == "CHAT_PUSH_BUSY"
        finally:
            release.set()
        first.result(timeout=10)
    assert len(endpoint.calls) == 1 and endpoint.post().json()["processing"] == "completed"


def test_stale_scheduler_query_snapshot_is_refreshed_after_lock(endpoint):
    query = endpoint.store.collection("chatPushEvents").where(filter=SimpleNamespace(field_path="inboxSynced", value=False))
    stale = list(query.stream())
    assert endpoint.post().status_code == 200
    original = endpoint.store.collection
    class StaleQuery:
        def where(self, *, filter):
            self.field = filter.field_path
            return self
        def limit(self, value):
            return self
        def stream(self):
            return iter(stale if self.field == "inboxSynced" else [])
    endpoint.store.collection = lambda name: StaleQuery()
    endpoint.tick()
    assert len(endpoint.calls) == 1


def test_shared_mysql_event_lock_is_released_on_failure(monkeypatch):
    from contextlib import nullcontext
    calls = []
    connection = SimpleNamespace(dialect=SimpleNamespace(name="mysql"), scalar=lambda *args: 1,
        execute=lambda statement, params: calls.append((str(statement), params["name"])))
    db = SimpleNamespace(engine=SimpleNamespace(connect=lambda: nullcontext(connection)))
    with pytest.raises(RuntimeError):
        with event_lock(db, EVENT_ID) as acquired:
            assert acquired
            raise RuntimeError("isolated failure")
    assert len(calls) == 1 and "RELEASE_LOCK" in calls[0][0]
    assert len(calls[0][1]) <= 64


def test_disabled_chat_does_not_dispatch(endpoint):
    endpoint.app.state.settings.fcm_chat_enabled = False
    assert endpoint.post().status_code == 503 and not endpoint.calls


@pytest.mark.parametrize("change", ["shop_inactive", "contract_ended", "mfa_enabled", "refresh_marker", "role_transition", "reply_membership_changed"])
def test_immediate_dispatch_rechecks_live_business_policy(endpoint, change):
    from datetime import date
    with endpoint.engine.begin() as conn:
        if change == "shop_inactive":
            table = endpoint.db.table("MSP_SPOT_MASTER")
            conn.execute(table.update().where(table.c.spot_master_id == "root").values(is_active=0))
        elif change == "contract_ended":
            table = endpoint.db.table("MSP_SPOT_MASTER")
            conn.execute(table.update().where(table.c.spot_master_id == "root").values(contract_end=date.today()-timedelta(days=2)))
        elif change == "mfa_enabled":
            table = endpoint.db.table("MSP_ADMIN")
            conn.execute(table.update().where(table.c.admin_id == "primary").values(mfa_method="email"))
        elif change == "refresh_marker":
            table = endpoint.db.table("MSP_REFRESH_TOKEN")
            conn.execute(table.update().values(user_agent="not-a-business-session"))
        elif change == "role_transition":
            table = endpoint.db.table("MSP_ADMIN_ROLE")
            conn.execute(table.update().where(table.c.admin_id == "primary").values(role_code="rental_manager"))
    if change == "reply_membership_changed":
        from app.chat import admin_uid
        endpoint.store.docs["chatShops/root/members/" + admin_uid("primary")]["canReply"] = False
    assert endpoint.post().status_code == 200 and not endpoint.calls
