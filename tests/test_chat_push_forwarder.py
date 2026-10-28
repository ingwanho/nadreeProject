"""Function forwarding is tested without metadata calls, real HTTP or FCM."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from chat.functions import chat_push_dispatch as forwarding


@pytest.fixture
def forwarder(monkeypatch):
    state = SimpleNamespace(posts=[], tokens=[], code=200, result={"status":"success", "processing":"completed"}, error=None)
    class Session:
        trust_env = True
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, **kwargs):
            state.posts.append((url, kwargs))
            if state.error:
                raise state.error
            return SimpleNamespace(status_code=state.code, json=lambda: state.result)
    def token(request, audience):
        state.tokens.append(audience)
        return "synthetic-service-token"
    monkeypatch.setattr(forwarding.requests, "Session", Session)
    monkeypatch.setattr(forwarding.id_token, "fetch_id_token", token)
    monkeypatch.delenv("CHAT_PUSH_BACKEND_URL", raising=False)
    monkeypatch.delenv("CHAT_PUSH_FORWARD_ENABLED", raising=False)
    state.send = lambda: forwarding.forward_event("b"*64, datetime.now(timezone.utc))
    return state


def test_function_forwards_only_event_id_with_oidc_and_no_redirects(forwarder):
    assert forwarder.send() == "completed"
    url, arguments = forwarder.posts[0]
    assert forwarder.tokens == [url]
    assert arguments["json"] == {"eventId": "b"*64}
    assert arguments["headers"] == {"Authorization": "Bearer synthetic-service-token"}
    assert arguments["allow_redirects"] is False


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503])
def test_callback_failure_is_not_reported_as_success(forwarder, status):
    forwarder.code = status
    with pytest.raises(forwarding.CallbackError, match="CHAT_PUSH_CALLBACK_HTTP_"+str(status)):
        forwarder.send()


def test_callback_exception_never_exposes_headers_or_credentials(forwarder):
    forwarder.error = RuntimeError("Authorization: Bearer synthetic-service-token")
    with pytest.raises(forwarding.CallbackError) as raised:
        forwarder.send()
    assert str(raised.value) == "CHAT_PUSH_CALLBACK_UNAVAILABLE"


@pytest.mark.parametrize("url", ["http://backend.example/internal/chat/push-events", "https://user:password@backend.example/internal/chat/push-events", "https://backend.example/wrong", "https://backend.example/internal/chat/push-events?token=forged"])
def test_unsafe_callback_configuration_is_rejected(forwarder, monkeypatch, url):
    monkeypatch.setenv("CHAT_PUSH_BACKEND_URL", url)
    with pytest.raises(forwarding.CallbackError, match="CHAT_PUSH_INVALID_BACKEND_URL"):
        forwarder.send()
    assert not forwarder.tokens and not forwarder.posts


def test_expired_events_are_not_forwarded_forever(forwarder):
    assert forwarding.forward_event("b"*64, datetime.now(timezone.utc)-timedelta(hours=2)) == "expired"
    assert not forwarder.posts


@pytest.mark.parametrize("identifier", ["A"*64, "invalid", None])
def test_malformed_event_id_never_reaches_backend(forwarder, identifier):
    with pytest.raises(forwarding.CallbackError, match="CHAT_PUSH_INVALID_EVENT_ID"):
        forwarding.forward_event(identifier, datetime.now(timezone.utc))
    assert not forwarder.posts


def test_forwarding_can_be_disabled_without_deleting_the_function(forwarder, monkeypatch):
    monkeypatch.setenv("CHAT_PUSH_FORWARD_ENABLED", "false")
    assert forwarder.send() == "disabled" and not forwarder.posts and not forwarder.tokens


@pytest.mark.parametrize("result", [None, [], {"status":"fail"}, {"status":"success","processing":"unknown"}])
def test_invalid_success_body_does_not_silently_acknowledge(forwarder, result):
    forwarder.result = result
    with pytest.raises(forwarding.CallbackError, match="CHAT_PUSH_INVALID_CALLBACK_RESPONSE"):
        forwarder.send()
