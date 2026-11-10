"""First SELF acceptance revokes rental access; erasure remains recoverable work."""
from contextlib import contextmanager
from datetime import timedelta
import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.account_deletion_store import request_id, utc
from app.chat import admin_uid
from app.errors import Problem
from app.security import GENERAL, PRIMARY, SESSION_MARKER, sign_user_access
from test_account_deletions import BASE, privacy, process, progress, submit
from test_admin_rental_exit import approve, live_rental, snapshot
from test_pending_reservation_approval import pending_bookings


def role_codes(ctx, ident):
    mapping = ctx["db"].table("MSP_ADMIN_ROLE")
    with ctx["engine"].connect() as conn:
        return set(conn.scalars(select(mapping.c.role_code).where(mapping.c.admin_id == ident)))


def transfer_count(ctx, name="MSP_RESERVATION_HISTORY"):
    history = ctx["db"].table(name)
    with ctx["engine"].connect() as conn:
        return conn.scalar(select(func.count()).select_from(history).where(history.c.event_type == "MANAGER_TRANSFERRED"))


def test_first_self_post_finishes_rental_exit_before_responding(privacy, signin):
    ctx = privacy
    own, primary = signin("general", fcmToken="isolated-current-device"), signin()
    revoked_before = list(ctx["revoked"])

    accepted, key, secret, _ = submit(ctx, own)

    assert accepted.status_code == 202, accepted.text
    data = accepted.json()
    assert data["scope"] == "SELF" and data["requestAccepted"] is True
    assert data["accessState"] == "REVOKED"
    assert data["personalDataState"] == "IN_PROGRESS" and data["completedAt"] is None
    row = ctx["store"].get(data["requestId"])
    assert row["steps"]["withdrawal"] is True and row["phase"] == "ERASING"
    assert not row["steps"].get("sql")
    assert GENERAL not in role_codes(ctx, "general")
    assert PRIMARY in role_codes(ctx, "primary")
    assert ctx["revoked"][len(revoked_before):] == [admin_uid("general")]
    admins, tokens = ctx["db"].table("MSP_ADMIN"), ctx["db"].table("MSP_REFRESH_TOKEN")
    with ctx["engine"].connect() as conn:
        account = conn.execute(select(admins).where(admins.c.admin_id == "general")).mappings().one()
        assert account["fcm_token"] is None
        # The initial response proves withdrawal, while the original profile
        # and provider identity remain for the existing privacy worker.
        assert account["is_active"] == 1 and account["email"] == "general@example.com"
        sessions = list(conn.execute(select(tokens).where(tokens.c.admin_id == "general",
            tokens.c.user_agent == SESSION_MARKER)).mappings())
        assert sessions and all(session["revoked_at"] is not None for session in sessions)
    assert ctx["deleted"] == [] and ctx["notices"] == []
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    assert ctx["client"].get("/nadreego/shop/admin", headers=primary).status_code == 200
    assert progress(ctx, key, secret).json()["accessState"] == "REVOKED"


def test_first_self_post_transfers_approved_work_without_changing_business_data(privacy, pending_bookings, signin):
    ctx = privacy
    _, book = pending_bookings
    own, primary = signin("general"), signin()
    ids = [book(i)["reservationId"] for i in range(2)]
    for ident in ids:
        approve(ctx, own, ident)
    live_rental(ctx, ids[0])
    before = snapshot(ctx)

    accepted, _, _, _ = submit(ctx, own)

    assert accepted.status_code == 202 and accepted.json()["accessState"] == "REVOKED"
    assert snapshot(ctx) == before
    assert transfer_count(ctx) == 2
    assert transfer_count(ctx, "MSP_RENTAL_CONTRACT_HISTORY") == 1
    history = ctx["db"].table("MSP_RESERVATION_HISTORY")
    with ctx["engine"].connect() as conn:
        moved = list(conn.execute(select(history).where(history.c.event_type == "MANAGER_TRANSFERRED")).mappings())
        assert {row["reservation_id"] for row in moved} == set(ids)
        assert {row["changed_by"] for row in moved} == {"primary"}
    inbox = ctx["client"].get("/nadreego/notifications?shopId=root", headers=primary)
    assert inbox.status_code == 200
    assert sum(item["eventType"] == "RESERVATION_MANAGER_TRANSFERRED" for item in inbox.json()["items"]) == 2


def test_same_key_replay_only_reads_receipt_and_never_repeats_handover(privacy, pending_bookings, signin):
    ctx = privacy
    _, book = pending_bookings
    own = signin("general")
    ident = book(0)["reservationId"]
    approve(ctx, own, ident)
    accepted, key, secret, body = submit(ctx, own)
    assert accepted.status_code == 202 and accepted.json()["accessState"] == "REVOKED"
    assert transfer_count(ctx) == 1

    def unexpected_revoke(uid):
        raise AssertionError("Receipt replay must not execute withdrawal")

    ctx["chat"].revoke = unexpected_revoke
    saved = ctx["store"].get(accepted.json()["requestId"])
    for headers in (own, {}):
        replay, _, _, _ = submit(ctx, headers, key=key, secret=secret, token=body["confirmationToken"])
        assert replay.status_code == 202
        assert replay.json()["requestId"] == accepted.json()["requestId"]
        assert replay.json()["accessState"] == "REVOKED"
    assert ctx["store"].get(saved["requestId"]) == saved
    assert transfer_count(ctx) == 1
    assert process(ctx)["completed"] == 1
    completed, _, _, _ = submit(ctx, {}, key=key, secret=secret, token=body["confirmationToken"])
    assert completed.status_code == 202 and completed.json()["personalDataState"] == "COMPLETED"
    assert transfer_count(ctx) == 1


def test_first_primary_post_still_waits_for_unfinished_subtree_work(privacy, pending_bookings, signin):
    ctx = privacy
    _, book = pending_bookings
    book(0)
    primary, general = signin(), signin("general")
    revoked = list(ctx["revoked"])
    before = snapshot(ctx)

    accepted, _, _, _ = submit(ctx, primary)

    assert accepted.status_code == 202
    assert accepted.json()["scope"] == "SUBTREE"
    assert accepted.json()["requestState"] == "WAITING_OBLIGATIONS"
    assert accepted.json()["accessState"] == "LIMITED_TO_SETTLEMENT"
    assert accepted.json()["outstandingWork"]["pendingReservations"] == 1
    assert ctx["store"].get(accepted.json()["requestId"])["steps"] == {}
    assert ctx["revoked"] == revoked and ctx["deleted"] == [] and ctx["notices"] == []
    assert snapshot(ctx) == before
    assert PRIMARY in role_codes(ctx, "primary") and GENERAL in role_codes(ctx, "general")
    assert ctx["client"].get("/nadreego/shop/admin", headers=primary).status_code == 200
    assert ctx["client"].get("/nadreego/shop/admin", headers=general).status_code == 200


def test_first_withdrawal_chat_failure_preserves_request_and_worker_can_recover(privacy, pending_bookings, signin):
    ctx = privacy
    _, book = pending_bookings
    own = signin("general")
    ident = book(0)["reservationId"]
    approve(ctx, own, ident)
    before = snapshot(ctx)

    def failed_revoke(uid):
        raise Problem(503, "CHAT_SYNC_FAILED")

    ctx["chat"].revoke = failed_revoke
    failed, key, secret, _ = submit(ctx, own)

    assert failed.status_code == 503
    assert failed.json()["errorCode"] == "DELETION_OUTCOME_UNKNOWN"
    assert failed.json().get("requestAccepted") is not False
    row = ctx["store"].get(request_id(key))
    assert row["phase"] == "WITHDRAWING" and not row["steps"].get("withdrawal")
    assert snapshot(ctx) == before and transfer_count(ctx) == 0
    assert GENERAL in role_codes(ctx, "general")
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 200
    assert progress(ctx, key, secret).status_code == 200
    ctx["chat"].revoke = lambda uid: ctx["revoked"].append(uid)
    result = process(ctx, at=utc() + timedelta(minutes=5))
    assert result["deferred"] == 0 and result["completed"] == 1
    assert transfer_count(ctx) == 1
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401


def test_sql_exit_survives_failed_erasing_checkpoint_and_worker_recovers_once(privacy, pending_bookings, signin):
    ctx = privacy
    _, book = pending_bookings
    own = signin("general")
    ident = book(0)["reservationId"]
    approve(ctx, own, ident)
    update_record, failures = ctx["store"].update, []

    def fail_checkpoint(ident, values):
        if values.get("phase") == "ERASING" and not failures:
            failures.append(True)
            raise RuntimeError("isolated checkpoint write failure")
        update_record(ident, values)

    ctx["store"].update = fail_checkpoint
    failed, key, secret, _ = submit(ctx, own)

    assert failed.status_code == 503 and failed.json()["errorCode"] == "DELETION_OUTCOME_UNKNOWN"
    row = ctx["store"].get(request_id(key))
    assert row["phase"] == "WITHDRAWING" and not row["steps"].get("withdrawal")
    assert GENERAL not in role_codes(ctx, "general")
    assert transfer_count(ctx) == 1
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    result = process(ctx, at=utc() + timedelta(minutes=5))
    assert result["deferred"] == 0 and result["completed"] == 1
    assert transfer_count(ctx) == 1
    assert progress(ctx, key, secret).json()["personalDataState"] == "COMPLETED"


def test_same_key_race_rechecks_saved_receipt_after_lock_before_authentication(privacy, signin):
    ctx = privacy
    own = signin("general")
    accepted, key, secret, body = submit(ctx, own)
    assert accepted.status_code == 202 and accepted.json()["accessState"] == "REVOKED"
    ident, original_get, reads = accepted.json()["requestId"], ctx["store"].get, []

    def before_lock_stale_lookup(value):
        if value == ident:
            reads.append(value)
            if len(reads) == 1:
                # The first request committed while this request was waiting
                # for its execution lock, and its old access token is revoked.
                return None
        return original_get(value)

    ctx["store"].get = before_lock_stale_lookup
    replay, _, _, _ = submit(ctx, own, key=key, secret=secret, token=body["confirmationToken"])

    assert replay.status_code == 202, replay.text
    assert replay.json()["requestId"] == ident and replay.json()["accessState"] == "REVOKED"
    assert len(reads) >= 2


def test_different_receipt_cannot_reuse_existing_general_request(privacy, signin):
    ctx = privacy
    own, primary = signin("general"), signin()
    accepted, key, _, _ = submit(ctx, own)
    ident = accepted.json()["requestId"]
    saved = ctx["store"].get(ident)
    wrong_secret = secrets.token_urlsafe(32)
    assert progress(ctx, key, wrong_secret).status_code == 404
    context = ctx["client"].get("/nadreego/admin/account-deletion-context", headers=primary)
    assert context.status_code == 200

    rejected = ctx["client"].post(BASE, headers={**primary, "Idempotency-Key": key,
        "Deletion-Receipt-Token": wrong_secret}, json={"confirmed": True,
            "confirmationToken": context.json()["confirmationToken"]})

    assert rejected.status_code == 409 and rejected.json()["errorCode"] == "IDEMPOTENCY_KEY_REUSED"
    assert ctx["store"].get(ident) == saved


def test_customer_token_cannot_submit_administrator_withdrawal(privacy, signin):
    ctx = privacy
    primary = signin()
    context = ctx["client"].get("/nadreego/admin/account-deletion-context", headers=primary)
    assert context.status_code == 200
    headers = {"Authorization": "Bearer " + sign_user_access(ctx["settings"], "isolated-customer"),
        "Idempotency-Key": str(uuid4()), "Deletion-Receipt-Token": secrets.token_urlsafe(32)}

    rejected = ctx["client"].post(BASE, headers=headers, json={"confirmed": True,
        "confirmationToken": context.json()["confirmationToken"]})

    assert rejected.status_code == 401 and rejected.json()["errorCode"] == "AUTH_REQUIRED"
    assert list(ctx["store"].records()) == []
    assert PRIMARY in role_codes(ctx, "primary")


def test_worker_skips_request_when_http_owns_execution_lock(privacy, signin, monkeypatch):
    ctx = privacy
    accepted, _, _, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]
    saved, locks = ctx["store"].get(ident), []

    @contextmanager
    def busy(db, request_ident, wait_seconds=0):
        locks.append((request_ident, wait_seconds))
        yield False

    def unexpected_process(*args, **kwargs):
        raise AssertionError("The worker must not process a locked request")

    monkeypatch.setattr("app.account_deletion_jobs.request_execution", busy)
    monkeypatch.setattr("app.account_deletion_jobs.process", unexpected_process)

    result = process(ctx)

    assert result["deferred"] == 0 and result["completed"] == 0
    assert locks == [(ident, 0)]
    assert ctx["store"].get(ident) == saved
    assert ctx["deleted"] == [] and ctx["notices"] == []


def test_worker_refreshes_request_after_execution_lock_before_processing(privacy, signin, monkeypatch):
    ctx = privacy
    accepted, _, _, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]
    assert ctx["store"].get(ident)["requestState"] == "PROCESSING"
    changed = []

    @contextmanager
    def changed_while_waiting(db, request_ident, wait_seconds=0):
        assert request_ident == ident
        ctx["store"].update(ident, {"requestState": "ACTION_REQUIRED",
            "nextAction": "CONTACT_OPERATOR", "attempts": 5})
        changed.append(True)
        yield True

    monkeypatch.setattr("app.account_deletion_jobs.request_execution", changed_while_waiting)

    result = process(ctx)

    assert changed == [True]
    assert result["deferred"] == 0 and result["completed"] == 0
    row = ctx["store"].get(ident)
    assert row["requestState"] == "ACTION_REQUIRED" and row["nextAction"] == "CONTACT_OPERATOR"
    assert row["attempts"] == 5
    assert ctx["deleted"] == [] and ctx["notices"] == []


def test_http_busy_rejects_before_acceptance_and_preserves_account(privacy, signin, monkeypatch):
    ctx = privacy
    own = signin("general", fcmToken="isolated-current-device")
    revoked, locks = list(ctx["revoked"]), []

    @contextmanager
    def busy(db, request_ident, *, wait_seconds=0):
        locks.append((request_ident, wait_seconds))
        yield False

    monkeypatch.setattr("app.account_deletions.request_execution", busy)

    rejected, key, _, _ = submit(ctx, own)

    assert rejected.status_code == 503
    assert rejected.json() == {"status": "fail", "errorCode": "DELETION_REQUEST_BUSY", "requestAccepted": False}
    assert locks == [(request_id(key), 10)]
    assert ctx["store"].get(request_id(key)) is None
    assert ctx["store"].active("general") is None
    assert list(ctx["store"].records()) == []
    assert ctx["revoked"] == revoked and ctx["notices"] == [] and ctx["deleted"] == []
    assert GENERAL in role_codes(ctx, "general")
    account = ctx["db"].table("MSP_ADMIN")
    with ctx["engine"].connect() as conn:
        assert conn.scalar(select(account.c.fcm_token).where(account.c.admin_id == "general")) == "isolated-current-device"
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 200


class LockConnection:
    """Connection double: record named-lock operations without any SQL engine."""

    def __init__(self, *, acquired=1, acquire_error=None, release_error=None):
        self.acquired = acquired
        self.acquire_error = acquire_error
        self.release_error = release_error
        self.events = []
        self.acquire_parameters = None
        self.release_parameters = None
        self.invalidated = False

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, error_type, error, traceback):
        self.events.append("exit")
        return False

    def scalar(self, statement, parameters):
        assert "GET_LOCK" in str(statement)
        self.events.append("acquire")
        self.acquire_parameters = parameters
        if self.acquire_error:
            raise self.acquire_error
        return self.acquired

    def execute(self, statement, parameters):
        assert "RELEASE_LOCK" in str(statement)
        self.events.append("release")
        self.release_parameters = parameters
        if self.release_error:
            raise self.release_error

    def invalidate(self):
        self.events.append("invalidate")
        self.invalidated = True


def lock_database(connection):
    return SimpleNamespace(engine=SimpleNamespace(dialect=SimpleNamespace(name="mysql"), connect=lambda: connection))


@pytest.mark.parametrize("body_failure", [False, True])
def test_mysql_request_lock_is_released_on_success_and_body_failure(body_failure):
    from app.account_deletion_scope import request_execution

    connection = LockConnection()
    db = lock_database(connection)
    try:
        with request_execution(db, "isolated-receipt", wait_seconds=3) as acquired:
            assert acquired is True
            if body_failure:
                raise ValueError("isolated body failure")
    except ValueError:
        assert body_failure

    assert connection.events == ["enter", "acquire", "release", "exit"]
    assert connection.invalidated is False
    name = connection.acquire_parameters["name"]
    assert name.startswith("nadree:delete:") and len(name.encode()) < 64
    assert "isolated-receipt" not in name
    assert connection.acquire_parameters["wait"] == 3
    assert connection.release_parameters == {"name": name}


def test_mysql_request_lock_acquisition_error_invalidates_connection():
    from app.account_deletion_scope import request_execution

    connection = LockConnection(acquire_error=RuntimeError("isolated lock acquisition failure"))
    with pytest.raises(RuntimeError, match="isolated lock acquisition failure"):
        with request_execution(lock_database(connection), "isolated-receipt"):
            pytest.fail("The body must not run when lock acquisition fails")

    assert connection.events == ["enter", "acquire", "invalidate", "exit"]
    assert connection.invalidated is True and connection.release_parameters is None


def test_mysql_request_lock_release_error_invalidates_connection():
    from app.account_deletion_scope import request_execution

    connection = LockConnection(release_error=RuntimeError("isolated lock release failure"))
    with pytest.raises(RuntimeError, match="isolated lock release failure"):
        with request_execution(lock_database(connection), "isolated-receipt") as acquired:
            assert acquired is True

    assert connection.events == ["enter", "acquire", "release", "invalidate", "exit"]
    assert connection.invalidated is True


def test_mysql_request_lock_busy_does_not_release_a_lock_owned_elsewhere():
    from app.account_deletion_scope import request_execution

    connection = LockConnection(acquired=0)
    with request_execution(lock_database(connection), "isolated-receipt") as acquired:
        assert acquired is False

    assert connection.events == ["enter", "acquire", "exit"]
    assert connection.invalidated is False and connection.release_parameters is None
