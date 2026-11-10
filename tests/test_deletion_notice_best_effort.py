"""Notification delivery is recorded independently from privacy erasure."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.account_deletion_jobs import contacts_for, notify
from app.chat import admin_uid
from app.errors import Problem
from app.security import GENERAL, PRIMARY
from app.account_deletion_store import utc
from test_account_deletions import privacy, process, progress, submit
from test_admin_rental_exit import approve, live_rental, snapshot
from test_pending_reservation_approval import pending_bookings


def failing_mailer(ctx, code="MAIL_UNAVAILABLE"):
    attempts = []

    def fail(email, ident, completed=False):
        attempts.append(completed)
        raise Problem(503, code)

    ctx["mailer"].send_deletion_notice = fail
    return attempts


def check_summary(row, stage, *, sent=0, failed=0, skipped=0, errors=(), timestamp_known=True):
    summary = row["notificationResults"][stage]
    assert summary["sentCount"] == sent
    assert summary["failedCount"] == failed
    assert summary["skippedCount"] == skipped
    if timestamp_known:
        assert summary["lastAttemptAt"] is not None
    else:
        assert summary["lastAttemptAt"] is None
    assert summary["errorCodes"] == list(errors)


@pytest.mark.parametrize("code", ["MAIL_UNAVAILABLE", "MAIL_NOT_CONFIGURED"])
def test_mail_failure_does_not_block_withdrawal_erasure_or_receipt(privacy, signin, code):
    ctx = privacy
    own = signin("general")
    accepted, key, secret, _ = submit(ctx, own)
    assert accepted.status_code == 202
    assert accepted.json()["accessState"] == "REVOKED"
    assert accepted.json()["personalDataState"] == "IN_PROGRESS"
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    assert ctx["deleted"] == [] and ctx["notices"] == []
    ident = accepted.json()["requestId"]
    attempts = failing_mailer(ctx, code)

    result = process(ctx)

    assert result["deferred"] == 0 and result["completed"] == 1
    assert attempts == [False, True]
    row = ctx["store"].get(ident)
    assert row["requestState"] == "COMPLETED"
    assert row["personalDataState"] == "COMPLETED" and row["accessState"] == "REVOKED"
    assert "privateContacts" not in row and "snapshot" not in row and "ownerId" not in row
    for stage in ("received", "completed"):
        check_summary(row, stage, failed=1, errors=[code])
        assert "general" not in repr(row["notificationResults"][stage])
    assert progress(ctx, key, secret).json()["requestState"] == "COMPLETED"
    assert ctx["deleted"] == [admin_uid("general")]
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    account = ctx["db"].table("MSP_ADMIN")
    with ctx["engine"].connect() as conn:
        erased = conn.execute(select(account).where(account.c.admin_id == "general")).mappings().one()
        assert erased["is_active"] == 0 and erased["email"] is None


def test_failure_only_of_completion_notice_does_not_block_completion(privacy, signin):
    ctx = privacy
    accepted, _, _, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]
    attempts = []

    def send(email, request_id, completed=False):
        attempts.append(completed)
        if completed:
            raise Problem(503, "MAIL_UNAVAILABLE")

    ctx["mailer"].send_deletion_notice = send
    result = process(ctx)

    assert result["deferred"] == 0 and result["completed"] == 1
    assert attempts == [False, True]
    row = ctx["store"].get(ident)
    check_summary(row, "received", sent=1)
    check_summary(row, "completed", failed=1, errors=["MAIL_UNAVAILABLE"])
    assert process(ctx)["processed"] == 0
    assert attempts == [False, True]


def test_missing_email_is_checkpointed_as_skipped_and_not_sent(privacy, signin):
    ctx = privacy
    account = ctx["db"].table("MSP_ADMIN")
    with ctx["engine"].begin() as conn:
        conn.execute(update(account).where(account.c.admin_id == "general").values(email=None))
    accepted, _, _, _ = submit(ctx, signin("general"))
    row = ctx["store"].get(accepted.json()["requestId"])
    contacts = contacts_for(ctx["settings"], row)

    notify(ctx["store"], row, ctx["mailer"], contacts)
    notify(ctx["store"], row, ctx["mailer"], contacts)

    saved = ctx["store"].get(row["requestId"])
    assert saved["receivedNotificationAttempts"] == ["general"]
    assert not saved.get("receivedNotified")
    check_summary(saved, "received", skipped=1, errors=["DELETION_NOTIFICATION_CONTACT_REQUIRED"])
    assert ctx["notices"] == []
    assert process(ctx)["completed"] == 1
    completed = ctx["store"].get(row["requestId"])
    check_summary(completed, "received", skipped=1, errors=["DELETION_NOTIFICATION_CONTACT_REQUIRED"])
    check_summary(completed, "completed", skipped=1, errors=["DELETION_NOTIFICATION_CONTACT_REQUIRED"])


def test_failed_notice_is_not_repeated_while_actual_shared_personal_data_waits_for_review(privacy, signin):
    from app.account_deletion_ops import act

    ctx = privacy
    ctx["store"].rows.pop("policy_retention")
    ctx["chats"].ref("chatRoomAccess/notice-review").set({
        "customerUid": "isolated-customer", "shopId": "root", "lastSequence": 1})
    message = ctx["chats"].ref("chatRoomAccess/notice-review/messages/customer")
    message.set({"senderUid": "isolated-customer", "text": "Contact general@example.com",
        "sequence": 1, "createdAt": utc()})
    accepted, _, _, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]
    attempts = failing_mailer(ctx)

    assert process(ctx)["deferred"] == 0
    first = ctx["store"].get(ident)
    assert first["requestState"] == "ACTION_REQUIRED"
    assert first["nextAction"] == "REVIEW_DATA_AND_RETENTION"
    assert first["reviewRequired"] == ["OTHER_PARTY_CHAT_MENTIONS"]
    assert first["receivedNotificationAttempts"] == ["general"]
    assert not first.get("receivedNotified")
    assert first["steps"]["withdrawal"] is True and first["steps"]["sql"] is True
    for minute in (5, 10):
        assert process(ctx, at=utc() + timedelta(minutes=minute))["deferred"] == 0
    assert attempts == [False]
    check_summary(ctx["store"].get(ident), "received", failed=1, errors=["MAIL_UNAVAILABLE"])
    # Simulate an operator resolving the actual shared-content issue; the
    # absent backup/log policy alone no longer requires a waiting state.
    cleaned = message.get().to_dict()
    cleaned["text"] = "Contact the branch representative"
    message.set(cleaned)
    act(ctx["db"], ctx["settings"], ctx["store"], "review", ident=ident,
        report={"reviewedCategories": first["reviewRequired"], "retainedData": []},
        operator="isolated-operator", evidence="Shared message cleaned in isolated test storage")
    assert process(ctx, at=utc() + timedelta(minutes=15))["completed"] == 1
    assert attempts == [False, True]
    assert ctx["store"].get(ident)["retentionReview"]["state"] == "PENDING"


def test_mail_failure_keeps_general_work_handover_and_business_data(privacy, pending_bookings, signin):
    ctx = privacy
    _, book = pending_bookings
    own, primary = signin("general"), signin()
    ident = book(0)["reservationId"]
    approve(ctx, own, ident)
    live_rental(ctx, ident)
    before = snapshot(ctx)
    accepted, _, _, _ = submit(ctx, own)
    assert accepted.status_code == 202
    assert accepted.json()["accessState"] == "REVOKED"
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    assert snapshot(ctx) == before
    with ctx["engine"].connect() as conn:
        for name in ("MSP_RESERVATION_HISTORY", "MSP_RENTAL_CONTRACT_HISTORY"):
            history = ctx["db"].table(name)
            assert conn.scalar(select(func.count()).select_from(history).where(
                history.c.event_type == "MANAGER_TRANSFERRED")) == 1
    failing_mailer(ctx)

    result = process(ctx)

    assert result["deferred"] == 0 and result["completed"] == 1
    assert snapshot(ctx) == before
    with ctx["engine"].connect() as conn:
        history = ctx["db"].table("MSP_RESERVATION_HISTORY")
        moved = list(conn.execute(select(history).where(history.c.event_type == "MANAGER_TRANSFERRED")).mappings())
        assert len(moved) == 1 and moved[0]["reservation_id"] == ident and moved[0]["changed_by"] == "primary"
        history = ctx["db"].table("MSP_RENTAL_CONTRACT_HISTORY")
        assert conn.scalar(select(func.count()).select_from(history).where(history.c.event_type == "MANAGER_TRANSFERRED")) == 1
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    assert ctx["client"].get("/nadreego/shop/admin", headers=primary).status_code == 200


def test_mail_failure_never_bypasses_primary_unfinished_work(privacy, pending_bookings, signin):
    ctx = privacy
    _, book = pending_bookings
    book(0)
    primary = signin()
    accepted, _, _, _ = submit(ctx, primary)
    ident = accepted.json()["requestId"]
    assert accepted.json()["requestState"] == "WAITING_OBLIGATIONS"
    attempts = failing_mailer(ctx)
    before, revoked = snapshot(ctx), list(ctx["revoked"])

    result = process(ctx)

    assert result["deferred"] == 0 and result["completed"] == 0
    row = ctx["store"].get(ident)
    assert row["requestState"] == "WAITING_OBLIGATIONS" and row["nextAction"] == "SETTLE_OUTSTANDING_WORK"
    assert row["outstandingWork"]["pendingReservations"] == 1
    check_summary(row, "received", failed=row["affectedAdminCount"], errors=["MAIL_UNAVAILABLE"])
    assert attempts == [False] * row["affectedAdminCount"]
    assert ctx["revoked"] == revoked and ctx["deleted"] == []
    assert snapshot(ctx) == before
    mapping = ctx["db"].table("MSP_ADMIN_ROLE")
    with ctx["engine"].connect() as conn:
        assert PRIMARY in conn.scalars(select(mapping.c.role_code).where(mapping.c.admin_id == "primary"))
        assert GENERAL in conn.scalars(select(mapping.c.role_code).where(mapping.c.admin_id == "general"))
    assert ctx["client"].get("/nadreego/shop/admin", headers=primary).status_code == 200


def test_untrusted_mail_failure_text_never_leaks_into_logs_or_receipt(privacy, signin, caplog):
    ctx = privacy
    accepted, key, secret, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]
    private_email, private_password = "unsafe-person@example.invalid", "private-password-marker"

    def fail(*args, **kwargs):
        raise RuntimeError(f"SMTP recipient {private_email} password {private_password}")

    ctx["mailer"].send_deletion_notice = fail
    result = process(ctx)

    assert result["deferred"] == 0 and result["completed"] == 1
    row = ctx["store"].get(ident)
    output = caplog.text + repr(row) + progress(ctx, key, secret).text
    assert private_email not in output and private_password not in output
    for stage in ("received", "completed"):
        check_summary(row, stage, failed=1, errors=["MAIL_UNAVAILABLE"])


def test_successful_notices_keep_legacy_success_lists_and_attempt_once(privacy, signin):
    ctx = privacy
    accepted, _, _, _ = submit(ctx, signin("general"))
    row = ctx["store"].get(accepted.json()["requestId"])
    contacts = contacts_for(ctx["settings"], row)
    for completed in (False, False, True, True):
        notify(ctx["store"], row, ctx["mailer"], contacts, completed=completed)
    saved = ctx["store"].get(row["requestId"])
    assert saved["receivedNotified"] == ["general"]
    assert saved["completionNotified"] == ["general"]
    assert saved["receivedNotificationAttempts"] == ["general"]
    assert saved["completionNotificationAttempts"] == ["general"]
    check_summary(saved, "received", sent=1)
    check_summary(saved, "completed", sent=1)
    assert len(ctx["notices"]) == 2


def test_old_success_checkpoint_is_not_resent_after_upgrade(privacy, signin):
    ctx = privacy
    accepted, _, _, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]
    ctx["store"].update(ident, {"receivedNotified": ["general"]})
    assert process(ctx)["completed"] == 1
    assert [notice[2] for notice in ctx["notices"]] == [True]
    # Old success lists contain no delivery timestamp; do not invent one.
    check_summary(ctx["store"].get(ident), "received", sent=1, timestamp_known=False)


def test_notification_checkpoint_write_error_is_not_swallowed_as_mail_failure(privacy, signin):
    ctx = privacy
    own = signin("general")
    accepted, _, _, _ = submit(ctx, own)
    ident = accepted.json()["requestId"]
    revoked = list(ctx["revoked"])
    ctx["store"].failure = RuntimeError("isolated notification checkpoint failure")

    result = process(ctx)

    assert result["deferred"] == 1 and result["completed"] == 0
    row = ctx["store"].get(ident)
    assert row["requestState"] == "RETRYING"
    assert not row.get("receivedNotificationAttempts") and row["steps"]["withdrawal"] is True
    assert row["accessState"] == "REVOKED" and row["personalDataState"] == "IN_PROGRESS"
    assert ctx["deleted"] == []
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    assert process(ctx, at=utc() + timedelta(minutes=5))["completed"] == 1
    assert ctx["revoked"] == revoked


def test_best_effort_notice_change_does_not_resume_contact_operator_request(privacy, signin):
    ctx = privacy
    own = signin("general")
    accepted, _, _, _ = submit(ctx, own)
    ident = accepted.json()["requestId"]
    ctx["store"].update(ident, {"requestState": "ACTION_REQUIRED", "nextAction": "CONTACT_OPERATOR", "attempts": 5})
    saved = ctx["store"].get(ident)
    attempts = failing_mailer(ctx)

    result = process(ctx)

    assert result["deferred"] == 0 and result["completed"] == 0
    assert ctx["store"].get(ident) == saved
    assert attempts == [] and ctx["deleted"] == []
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
