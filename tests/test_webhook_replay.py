from datetime import datetime, timedelta, timezone
import json

from app.paypal import WebhookReplayGuard, handle_webhook, webhook_time_is_fresh
from app.rental_schema import metadata as rental_metadata


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key):
        self.values.pop(key, None)


class FakePayPal:
    def __init__(self, settings):
        self.settings = settings
        self.verify_calls = 0

    def verify(self, event, headers):
        self.verify_calls += 1
        return True


def webhook_input():
    current = datetime.now(timezone.utc)
    event = {
        "id": "WH-REPLAY-1",
        "create_time": current.isoformat().replace("+00:00", "Z"),
        "event_type": "UNSUPPORTED.EVENT",
        "resource_type": "unknown",
        "resource": {"id": "RESOURCE-1"},
    }
    headers = {
        "paypal-transmission-id": "TRANSMISSION-1",
        "paypal-transmission-time": current.isoformat().replace("+00:00", "Z"),
        "paypal-transmission-sig": "signature",
        "paypal-cert-url": "https://api.paypal.com/cert",
        "paypal-auth-algo": "SHA256withRSA",
    }
    return event, headers


def test_webhook_timestamp_must_be_within_five_minutes():
    current = datetime.now(timezone.utc)
    fresh = current.isoformat().replace("+00:00", "Z")
    stale = (current - timedelta(minutes=5, seconds=1)).isoformat().replace("+00:00", "Z")
    assert webhook_time_is_fresh(fresh)
    assert not webhook_time_is_fresh(stale)
    assert not webhook_time_is_fresh("not-a-time")


def test_replay_guard_allows_one_inflight_request_and_caches_verified():
    redis = FakeRedis()
    guard = WebhookReplayGuard(redis, "SANDBOX")
    digest = "a" * 64
    assert guard.begin(digest) == "acquired"
    assert guard.begin(digest) == "busy"
    guard.release(digest)
    guard.mark_verified(digest)
    assert guard.begin(digest) == "verified"


def test_webhook_replay_uses_verified_cache_and_db_idempotency(setup):
    rental_metadata.create_all(setup["engine"])
    event, headers = webhook_input()
    raw = json.dumps(event)
    client = FakePayPal(setup["settings"])
    redis = FakeRedis()

    assert handle_webhook(setup["db"], client, raw, event, headers, replay_store=redis) == 200
    assert handle_webhook(setup["db"], client, raw, event, headers, replay_store=redis) == 200
    assert client.verify_calls == 1
