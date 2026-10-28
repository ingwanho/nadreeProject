"""Real SQL transactions and delivery logic; Firestore/FCM are isolated fakes."""
from copy import deepcopy
from datetime import timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app import chat_push, chat_sync, fcm
from app.chat import admin_uid
from app.fcm import FcmSender
from app.rental_schema import metadata
from app.security import SESSION_MARKER, fingerprint, now


class Snapshot:
    def __init__(self, reference):
        self.reference, self.id = reference, reference.path.split("/")[-1]
        self.value = deepcopy(reference.store.docs.get(reference.path))

    def to_dict(self):
        return deepcopy(self.value)


class Ref:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def get(self):
        return Snapshot(self)

    def update(self, values):
        if self.store.failure and self.store.failure(values):
            self.store.failure = None
            raise RuntimeError("isolated checkpoint failure")
        self.store.docs[self.path].update(deepcopy(values))


class Query:
    def __init__(self, store, name):
        self.store, self.name, self.maximum = store, name, 500

    def where(self, *, filter):
        self.field, self.value = filter.field_path, filter.value
        return self

    def limit(self, maximum):
        self.maximum = maximum
        return self

    def stream(self):
        paths = [path for path, data in self.store.docs.items()
                 if path.startswith(self.name + "/") and data.get(self.field) is self.value]
        return iter(Snapshot(self.store.ref(path)) for path in paths[:self.maximum])


class Store:
    def __init__(self):
        self.docs, self.failure, self.db = {}, None, self

    def ref(self, path):
        return Ref(self, path)

    def collection(self, name):
        return Query(self, name)


@pytest.fixture
def env(setup, monkeypatch):
    assert setup["engine"].dialect.name == "sqlite"
    metadata.create_all(setup["engine"])
    clock = SimpleNamespace(at=now().replace(microsecond=0))
    monkeypatch.setattr(chat_push, "now", lambda: clock.at)
    monkeypatch.setattr(fcm, "_utc_now", lambda: clock.at)
    store, calls = Store(), []
    sender = FcmSender(SimpleNamespace(fcm_project_id="isolated", fcm_client_email="isolated@example.com",
                                       fcm_private_key=SecretStr("synthetic-test-key")))
    outcomes = []

    def send(notification, *, detailed=False):
        assert detailed
        calls.append(deepcopy(notification))
        outcome = outcomes.pop(0) if outcomes else {"accepted": [v["id"] for v in notification["recipients"]]}
        if isinstance(outcome, BaseException):
            raise outcome
        return {**{key: [item for item in notification["recipients"] if item["id"] in outcome.get(key, [])]
                   for key in ("accepted", "invalid", "failed", "retryable")}, "retry_after": outcome.get("retry_after")}

    monkeypatch.setattr(sender, "_send", send)

    def add_admin(ident="primary"):
        token, sid, business = "synthetic-token-" + ident, "chat-" + ident, "business-" + ident
        admins, sessions = setup["db"].table("MSP_ADMIN"), setup["db"].table("MSP_REFRESH_TOKEN")
        with setup["engine"].begin() as conn:
            conn.execute(admins.update().where(admins.c.admin_id == ident).values(fcm_token=token, fcm_token_updated_at=clock.at))
            conn.execute(sessions.insert().values(token_id=business, admin_id=ident, token_hash=fingerprint(business),
                user_agent=SESSION_MARKER, issued_at=clock.at-timedelta(minutes=1), expires_at=clock.at+timedelta(days=1)))
        uid = admin_uid(ident)
        store.docs["chatUsers/" + uid] = {"active": True, "expiresAt": (clock.at+timedelta(days=1)).replace(tzinfo=timezone.utc),
            "sessionId": sid, "businessSessionId": business, "shopIds": ["root"]}
        store.docs["chatPushTokens/" + uid] = {"token": token, "sessionId": sid}
        store.docs["chatPushTokenOwners/" + fingerprint(token)] = {"uid": uid, "sessionId": sid}
        store.docs["chatShops/root/members/" + uid] = {"active": True, "canReply": ident == "primary"}

    add_admin()
    store.docs["chatPushEvents/event"] = {"senderKind": "customer", "shopId": "root", "roomId": "room",
        "customerUid": "synthetic-customer", "createdAt": clock.at.replace(tzinfo=timezone.utc), "inboxSynced": False}
    value = SimpleNamespace(**setup, clock=clock, store=store, chat=SimpleNamespace(store=lambda: store, settings=setup["app"].state.settings),
                            sender=sender, calls=calls, outcomes=outcomes, add_admin=add_admin)
    value.tick = lambda: chat_push.sync_inbox(setup["db"], value.chat, sender)
    value.event = lambda: store.docs["chatPushEvents/event"]
    value.states = lambda: value.event()["pushDelivery"]["recipients"]
    try:
        yield value
    finally:
        sender.close(wait=True)


def inbox_count(env):
    with env.engine.connect() as conn:
        return conn.scalar(select(func.count()).select_from(metadata.tables["MSP_RENTAL_NOTIFICATION"]))


def test_success_is_checkpointed_without_replaying_or_copying_raw_tokens(env):
    assert env.tick()["accepted"] == 1
    env.tick()
    assert len(env.calls) == inbox_count(env) == 1
    assert env.event()["inboxSynced"] is True and env.event()["pushPending"] is False
    assert env.states()[0]["status"] == "accepted"
    assert "synthetic-token-primary" not in str(env.event())


def test_transient_failure_survives_next_run_and_obeys_backoff(env):
    env.outcomes.append({"retryable": ["primary"]})
    assert env.tick()["retry"] == 1
    assert env.event()["inboxSynced"] and env.event()["pushPending"]
    env.clock.at += timedelta(seconds=29)
    env.tick()
    assert len(env.calls) == 1
    env.clock.at += timedelta(seconds=1)
    assert env.tick()["accepted"] == 1
    assert len(env.calls) == 2 and inbox_count(env) == 1
    assert env.calls[0]["data"]["eventId"] == env.calls[1]["data"]["eventId"]


def test_sql_commit_followed_by_firestore_ack_failure_does_not_lose_push(env):
    env.store.failure = lambda values: set(values) == {"inboxSynced"}
    assert env.tick()["deferred"] == 1
    assert inbox_count(env) == 1 and env.event()["pushPending"] and not env.calls
    assert env.tick()["accepted"] == 1
    assert len(env.calls) == inbox_count(env) == 1


def test_initial_checkpoint_failure_does_not_commit_or_send(env):
    env.store.failure = lambda values: "pushDelivery" in values
    assert env.tick()["deferred"] == 1
    assert inbox_count(env) == 0 and not env.calls
    assert env.tick()["accepted"] == 1


def test_process_exit_after_attempt_checkpoint_is_recoverable(env):
    env.outcomes.append(SystemExit("isolated process exit"))
    with pytest.raises(SystemExit):
        env.tick()
    assert env.event()["pushPending"] and env.event()["inboxSynced"]
    env.clock.at += timedelta(seconds=30)
    assert env.tick()["accepted"] == 1


def test_acceptance_checkpoint_failure_is_at_least_once_with_stable_event_id(env):
    env.store.failure = lambda values: any(row["status"] == "accepted" for row in values.get("pushDelivery", {}).get("recipients", []))
    assert env.tick()["deferred"] == 1
    assert env.event()["pushPending"]
    env.clock.at += timedelta(seconds=30)
    assert env.tick()["accepted"] == 1
    assert len(env.calls) == 2 and env.calls[0]["data"] == env.calls[1]["data"]


def test_partial_success_retries_only_the_unsent_recipient(env):
    env.add_admin("general")
    env.outcomes.append({"accepted": ["primary"], "retryable": ["general"]})
    env.tick()
    env.clock.at += timedelta(seconds=30)
    env.tick()
    assert [item["id"] for item in env.calls[1]["recipients"]] == ["general"]
    assert {row["status"] for row in env.states()} == {"accepted"}


@pytest.mark.parametrize("change", ["logout", "business_expiry", "chat_revoke", "chat_expiry", "chat_session", "token", "owner", "scope", "role", "membership"])
def test_retry_never_crosses_a_changed_security_context(env, change):
    env.outcomes.append({"retryable": ["primary"]})
    env.tick()
    uid, token = admin_uid("primary"), "synthetic-token-primary"
    with env.engine.begin() as conn:
        sessions, admins = env.db.table("MSP_REFRESH_TOKEN"), env.db.table("MSP_ADMIN")
        if change == "logout":
            conn.execute(sessions.update().values(revoked_at=env.clock.at))
        elif change == "business_expiry":
            conn.execute(sessions.update().values(expires_at=env.clock.at))
        elif change == "token":
            conn.execute(admins.update().where(admins.c.admin_id == "primary").values(fcm_token="changed-test-token"))
        elif change in ("scope", "role"):
            table = env.db.table("MSP_ADMIN_SPOT_SCOPE" if change == "scope" else "MSP_ADMIN_ROLE")
            conn.execute(table.delete().where(table.c.admin_id == "primary"))
    if change == "chat_revoke":
        env.store.docs["chatUsers/" + uid]["active"] = False
    elif change == "chat_expiry":
        env.store.docs["chatUsers/" + uid]["expiresAt"] = env.clock.at.replace(tzinfo=timezone.utc)
    elif change == "chat_session":
        env.store.docs["chatUsers/" + uid]["sessionId"] = "replacement-session"
    elif change == "owner":
        env.store.docs["chatPushTokenOwners/" + fingerprint(token)] = {"uid": "other", "sessionId": "other"}
    elif change == "membership":
        env.store.docs["chatShops/root/members/" + uid]["active"] = False
    env.clock.at += timedelta(seconds=30)
    assert env.tick()["skipped"] == 1
    assert len(env.calls) == 1 and not env.event()["pushPending"]


def test_no_session_at_first_processing_is_not_replayed_after_login(env):
    env.store.docs["chatUsers/" + admin_uid("primary")]["active"] = False
    env.tick()
    env.store.docs["chatUsers/" + admin_uid("primary")]["active"] = True
    env.tick()
    assert not env.calls and env.states() == [] and inbox_count(env) == 1


def test_legacy_completed_event_is_not_replayed(env):
    env.event()["inboxSynced"] = True
    before = deepcopy(env.event())
    env.tick()
    assert env.event() == before and not env.calls


def test_existing_sql_inbox_does_not_prevent_first_delivery(env):
    from app.notifications import record_notification
    from sqlalchemy.orm import Session
    with Session(env.engine) as session, session.begin():
        record_notification(env.db, session, "root", "CHAT_MESSAGE", "CHAT", "room", "chat:event")
    assert env.tick()["accepted"] == 1 and inbox_count(env) == 1


def test_retry_limit_and_expiry_stop_repeated_failures(env):
    env.outcomes.extend([{"retryable": ["primary"]}] * 5)
    for _ in range(5):
        env.tick()
        env.clock.at = chat_push.utc(env.states()[0]["nextAttemptAt"]).replace(tzinfo=None)
    assert len(env.calls) == 5 and env.states()[0]["status"] == "failed"
    env.tick()
    assert len(env.calls) == 5 and not env.event()["pushPending"]


def test_old_event_expires_without_sending(env):
    env.event()["createdAt"] -= timedelta(hours=2)
    env.tick()
    assert env.states()[0]["status"] == "failed" and not env.calls


def test_retry_after_survives_the_scheduler_tick(env):
    env.outcomes.append({"retryable": ["primary"], "retry_after": 120})
    env.tick()
    env.clock.at += timedelta(seconds=90)
    env.tick()
    assert len(env.calls) == 1
    env.clock.at += timedelta(seconds=30)
    assert env.tick()["accepted"] == 1


def test_unregistered_token_is_terminal_and_conditionally_cleared(env):
    env.outcomes.append({"invalid": ["primary"]})
    env.tick()
    with env.engine.connect() as conn:
        admins = env.db.table("MSP_ADMIN")
        assert conn.scalar(select(admins.c.fcm_token).where(admins.c.admin_id == "primary")) is None
    assert env.states()[0]["status"] == "failed" and not env.event()["pushPending"]


def test_one_bad_event_does_not_block_others(env):
    env.store.docs["chatPushEvents/bad-event"] = {"inboxSynced": False}
    result = env.tick()
    assert result["accepted"] == result["deferred"] == 1


def test_network_exception_remains_retryable(env):
    env.outcomes.append(TimeoutError("isolated network failure"))
    assert env.tick()["retry"] == 1
    env.clock.at += timedelta(seconds=30)
    assert env.tick()["accepted"] == 1


def test_missing_configuration_is_not_marked_delivered(env):
    env.sender.settings.fcm_private_key = SecretStr("")
    assert env.tick()["retry"] == 1
    assert not env.calls and env.event()["pushPending"]
    env.sender.settings.fcm_private_key = SecretStr("synthetic-test-key")
    env.clock.at += timedelta(seconds=30)
    assert env.tick()["accepted"] == 1


def test_token_cleanup_failure_does_not_replay_another_accepted_recipient(env, monkeypatch):
    env.add_admin("general")
    env.outcomes.append({"accepted": ["primary"], "invalid": ["general"]})
    def fail(*args):
        raise RuntimeError("isolated cleanup outage")
    monkeypatch.setattr(env.sender, "_clear_invalid_tokens", fail)
    assert env.tick()["accepted"] == 1
    env.tick()
    assert len(env.calls) == 1 and not env.event()["pushPending"]


def test_sql_session_is_rechecked_immediately_before_provider_call(env, monkeypatch):
    original, count = FcmSender._current_recipients, 0
    def checking(db, notification):
        nonlocal count
        count += 1
        if count == 3:
            table = db.table("MSP_REFRESH_TOKEN")
            with env.engine.begin() as conn:
                conn.execute(table.update().values(revoked_at=env.clock.at))
        return original(db, notification)
    monkeypatch.setattr(FcmSender, "_current_recipients", staticmethod(checking))
    assert env.tick()["skipped"] == 1
    assert not env.calls and not env.event()["pushPending"]


def test_admin_message_is_delivered_only_to_the_matching_customer(env):
    uid, token, sid, business = "synthetic-customer", "synthetic-customer-token", "customer-chat", "customer-business"
    users, sessions = env.db.table("MSP_RENTAL_USER"), env.db.table("MSP_RENTAL_USER_REFRESH_TOKEN")
    with env.engine.begin() as conn:
        conn.execute(users.insert().values(uid_token=uid, fcm_token=token, fcm_token_updated_at=env.clock.at))
        conn.execute(sessions.insert().values(token_id=business, uid_token=uid, token_hash=fingerprint(business),
            issued_at=env.clock.at, expires_at=env.clock.at+timedelta(days=1)))
    env.store.docs["chatUsers/" + uid] = {"active": True, "expiresAt": (env.clock.at+timedelta(days=1)).replace(tzinfo=timezone.utc),
        "sessionId": sid, "businessSessionId": business, "shopIds": []}
    env.store.docs["chatPushTokens/" + uid] = {"token": token, "sessionId": sid}
    env.store.docs["chatPushTokenOwners/" + fingerprint(token)] = {"uid": uid, "sessionId": sid}
    env.event()["senderKind"] = "admin"
    assert env.tick()["accepted"] == 1
    assert [item["id"] for item in env.calls[0]["recipients"]] == [uid]


def test_provider_outcomes_and_existing_best_effort_result_contract(env, monkeypatch):
    from firebase_admin import messaging
    class Error(Exception):
        def __init__(self, code):
            self.code = code
    errors = [None, Error("unavailable"), Error("invalid-argument"), Error("unregistered")]
    monkeypatch.setattr(messaging, "send_each_for_multicast", lambda *args, **kwargs:
                        SimpleNamespace(responses=[SimpleNamespace(exception=error) for error in errors]))
    monkeypatch.setattr(env.sender, "_firebase_app", lambda: None)
    message = {"event": "CHAT_MESSAGE", "title": "test", "body": "test", "data": {},
               "recipients": [{"id": str(n), "token": "synthetic-" + str(n)} for n in range(4)]}
    result = FcmSender._send(env.sender, message, detailed=True)
    assert [item["id"] for item in result["accepted"]] == ["0"]
    assert [item["id"] for item in result["retryable"]] == ["1"]
    assert [item["id"] for item in result["failed"]] == ["2"]
    assert [item["id"] for item in result["invalid"]] == ["3"]
    assert len(FcmSender._send(env.sender, message)) == 3


@pytest.mark.parametrize("lock_acquired", [True, False])
def test_mysql_lock_excludes_second_scheduler_and_is_released(monkeypatch, lock_acquired):
    from contextlib import nullcontext
    statements, runs = [], []
    connection = SimpleNamespace(dialect=SimpleNamespace(name="mysql"),
        scalar=lambda *args: int(lock_acquired), execute=lambda statement, params: statements.append(str(statement)))
    db = SimpleNamespace(engine=SimpleNamespace(connect=lambda: nullcontext(connection)))
    monkeypatch.setattr(chat_sync, "_run", lambda *args: runs.append(True))
    chat_sync.run(db, None, None)
    assert bool(runs) is lock_acquired
    assert bool(statements) is lock_acquired
    if lock_acquired:
        assert "RELEASE_LOCK" in statements[0]


def test_push_processing_precedes_catalogue_and_booking_scan(env, monkeypatch):
    order = []
    monkeypatch.setattr(chat_sync, "reconcile_sessions", lambda *args: order.append("sessions"))
    monkeypatch.setattr(chat_sync, "sync_inbox", lambda *args: order.append("push"))
    monkeypatch.setattr(chat_sync, "sync_catalogue", lambda *args: order.append("catalogue"))
    chat_sync.run(env.db, env.chat, env.sender)
    assert order == ["sessions", "push", "catalogue"]
