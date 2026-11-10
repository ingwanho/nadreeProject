"""Unverified log/backup retention must not hide completed active-system erasure."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.account_deletion_ops import act
from app.account_deletion_store import utc
from app.chat import admin_uid
from app.errors import Problem
from test_account_deletions import privacy, process, progress, submit


COPY_CATEGORIES = {"COMPANY_RESTRICTED_BACKUP", "COMPANY_LOG_RETENTION"}


def company_copies(row):
    copies = {item["category"]: item for item in row["residualCopies"] if item["category"] in COPY_CATEGORIES}
    assert set(copies) == COPY_CATEGORIES
    return copies


def pending_retention(row):
    assert row["retentionReview"]["state"] == "PENDING"
    assert row["retentionReview"]["checkedAt"] is not None
    assert not row.get("policyEvidenceHash")
    for item in company_copies(row).values():
        assert item["reviewState"] == "PENDING" and item["requestedMaxDays"] == 30
        assert "deleteBy" not in item


@pytest.mark.parametrize("invalid_policy", [
    "MISSING", "EXPIRED", "UNVERIFIED", "ACTIVE_STORES_UNREVIEWED", "MALFORMED_DATE",
    "MALFORMED_DAYS", "NOT_A_DOCUMENT", "DAYS_OUT_OF_RANGE", "BOOLEAN_DAYS", "FRACTIONAL_DAYS",
])
def test_unverified_policy_does_not_delay_real_active_system_erasure(privacy, signin, invalid_policy):
    ctx = privacy
    if invalid_policy == "MISSING":
        ctx["store"].rows.pop("policy_retention")
    elif invalid_policy == "NOT_A_DOCUMENT":
        original_get = ctx["store"].get
        ctx["store"].get = lambda value: ["invalid-record"] if value == "policy_retention" else original_get(value)
    else:
        policy = dict(ctx["store"].rows["policy_retention"])
        policy.update({
            "EXPIRED": {"reviewUntil": utc() - timedelta(seconds=1)},
            "UNVERIFIED": {"verified": False},
            "ACTIVE_STORES_UNREVIEWED": {"activeStoresReviewed": False},
            "MALFORMED_DATE": {"reviewUntil": "invalid-review-date"},
            "MALFORMED_DAYS": {"logMaxDays": "invalid-days"},
            "DAYS_OUT_OF_RANGE": {"backupMaxDays": 31},
            "BOOLEAN_DAYS": {"logMaxDays": True},
            "FRACTIONAL_DAYS": {"backupMaxDays": 1.5},
        }[invalid_policy])
        ctx["store"].rows["policy_retention"] = policy
    ctx["chats"].ref("chatRoomAccess/policy-check").set({
        "customerUid": "isolated-customer", "shopId": "root", "lastSequence": 1})
    message = ctx["chats"].ref("chatRoomAccess/policy-check/messages/own")
    message.set({"senderUid": admin_uid("general"), "text": "Disposable private message",
        "sequence": 1, "createdAt": utc()})
    own = signin("general")
    accepted, key, secret, _ = submit(ctx, own)
    assert accepted.status_code == 202 and accepted.json()["accessState"] == "REVOKED"

    result = process(ctx)

    assert result["completed"] == 1 and result["deferred"] == 0
    row = ctx["store"].get(accepted.json()["requestId"])
    assert row["requestState"] == "COMPLETED" and row["personalDataState"] == "COMPLETED"
    assert row["accessState"] == "REVOKED" and row["completedAt"] is not None
    assert row["completionScope"] == "COMPANY_ACTIVE_SYSTEMS" and row["nextAction"] == "NONE"
    pending_retention(row)
    assert "snapshot" not in row and "ownerId" not in row and "privateContacts" not in row
    assert "general@example.com" not in repr(row)
    erased_message = message.get().to_dict()
    assert erased_message["senderUid"] == "deleted-admin" and erased_message["text"] == "[Deleted]"
    assert ctx["deleted"] == [admin_uid("general")]
    assert len(ctx["notices"]) == 2 and ctx["notices"][-1][2] is True
    admins = ctx["db"].table("MSP_ADMIN")
    with ctx["engine"].connect() as conn:
        account = conn.execute(select(admins).where(admins.c.admin_id == "general")).mappings().one()
        assert account["is_active"] == 0 and account["email"] is None and account["admin_name"] is None
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    public = progress(ctx, key, secret)
    assert public.status_code == 200 and public.json()["personalDataState"] == "COMPLETED"
    assert "retentionReview" not in public.json()
    assert all("deleteBy" not in item for item in company_copies(public.json()).values())


def test_policy_lookup_exception_records_pending_without_leaking_error_text(privacy, signin, caplog):
    ctx = privacy
    accepted, key, secret, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]
    original_get = ctx["store"].get
    private_email, private_secret = "policy-owner@example.invalid", "private-policy-secret-marker"

    def policy_unavailable(value):
        if value == "policy_retention":
            raise RuntimeError(f"Storage detail for {private_email}: {private_secret}")
        return original_get(value)

    ctx["store"].get = policy_unavailable

    result = process(ctx)

    assert result["completed"] == 1 and result["deferred"] == 0
    row = ctx["store"].get(ident)
    pending_retention(row)
    assert row["requestState"] == "COMPLETED" and row["personalDataState"] == "COMPLETED"
    output = caplog.text + repr(row) + progress(ctx, key, secret).text
    assert private_email not in output and private_secret not in output


@pytest.mark.parametrize("log_days,backup_days", [(7, 14), (0, 0), (30, 30)])
def test_verified_policy_keeps_actual_recorded_deadlines(privacy, signin, log_days, backup_days):
    ctx = privacy
    act(ctx["db"], ctx["settings"], ctx["store"], "policy", operator="isolated-operator",
        evidence="Isolated verified retention settings", log_days=log_days, backup_days=backup_days)
    accepted, _, _, _ = submit(ctx, signin("general"))

    result = process(ctx)

    assert result["completed"] == 1 and result["deferred"] == 0
    row = ctx["store"].get(accepted.json()["requestId"])
    assert row["retentionReview"]["state"] == "VERIFIED"
    assert row["retentionReview"]["checkedAt"] is not None and row["policyEvidenceHash"]
    copies = company_copies(row)
    for category, days in (("COMPANY_RESTRICTED_BACKUP", backup_days), ("COMPANY_LOG_RETENTION", log_days)):
        assert copies[category]["reviewState"] == "VERIFIED"
        assert copies[category]["deleteBy"] - row["completedAt"] == timedelta(days=days)


def test_actual_shared_message_personal_information_still_requires_resolution(privacy, signin):
    ctx = privacy
    ctx["store"].rows.pop("policy_retention")
    ctx["chats"].ref("chatRoomAccess/shared-review").set({
        "customerUid": "isolated-customer", "shopId": "root", "lastSequence": 1})
    message = ctx["chats"].ref("chatRoomAccess/shared-review/messages/customer")
    original = {"senderUid": "isolated-customer", "text": "Ask general@example.com for assistance",
        "sequence": 1, "createdAt": utc()}
    message.set(original)
    accepted, key, secret, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]

    result = process(ctx)

    assert result["completed"] == 0 and result["deferred"] == 0
    row = ctx["store"].get(ident)
    assert row["requestState"] == "ACTION_REQUIRED" and row["nextAction"] == "REVIEW_DATA_AND_RETENTION"
    assert row["personalDataState"] == "IN_PROGRESS" and row["completedAt"] is None
    assert row["reviewRequired"] == ["OTHER_PARTY_CHAT_MENTIONS"]
    assert row["retentionReview"]["state"] == "PENDING"
    assert message.get().to_dict() == original
    assert row["steps"]["withdrawal"] is True and row["steps"]["sql"] is True
    assert process(ctx, at=utc() + timedelta(minutes=5))["completed"] == 0
    assert progress(ctx, key, secret).json()["personalDataState"] == "IN_PROGRESS"


def test_actual_provider_deletion_failure_is_not_treated_as_retention_review(privacy, signin):
    ctx = privacy
    ctx["store"].rows.pop("policy_retention")
    accepted, _, _, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]

    def fail_identity_delete(value):
        raise Problem(503, "CUSTOMER_FIREBASE_AUTH_DELETE_FAILED")

    ctx["chat"].delete_admin_identity = fail_identity_delete

    result = process(ctx)

    assert result["completed"] == 0 and result["deferred"] == 1
    row = ctx["store"].get(ident)
    assert row["requestState"] == "RETRYING" and row["personalDataState"] == "IN_PROGRESS"
    assert row["completedAt"] is None
    assert row["steps"]["withdrawal"] is True and row["steps"]["sql"] is True
    ctx["chat"].delete_admin_identity = lambda value: True
    assert process(ctx, at=utc() + timedelta(minutes=5))["completed"] == 1
    pending_retention(ctx["store"].get(ident))


def test_other_active_service_retention_is_preserved_without_verified_policy(privacy, signin):
    ctx = privacy
    ctx["store"].rows.pop("policy_retention")
    roles = ctx["db"].table("MSP_ADMIN_ROLE")
    with ctx["engine"].begin() as conn:
        conn.execute(roles.insert().values(admin_id="general", role_code="viewer"))
    accepted, _, _, _ = submit(ctx, signin("general"))

    result = process(ctx)

    assert result["completed"] == 1 and result["deferred"] == 0
    row = ctx["store"].get(accepted.json()["requestId"])
    assert row["requestState"] == "COMPLETED_WITH_RETENTION" and row["personalDataState"] == "COMPLETED"
    assert row["retainedData"][0]["retentionBasis"] == "OTHER_ACTIVE_SERVICE_RELATIONSHIP"
    pending_retention(row)
    admins = ctx["db"].table("MSP_ADMIN")
    with ctx["engine"].connect() as conn:
        assert conn.scalar(select(admins.c.email).where(admins.c.admin_id == "general")) == "general@example.com"
        assert set(conn.scalars(select(roles.c.role_code).where(roles.c.admin_id == "general"))) == {"viewer"}


def test_operator_inspect_exposes_retention_review_without_new_public_field(privacy, signin):
    ctx = privacy
    ctx["store"].rows.pop("policy_retention")
    accepted, key, secret, _ = submit(ctx, signin("general"))
    assert process(ctx)["completed"] == 1
    ident = accepted.json()["requestId"]

    inspected = act(ctx["db"], ctx["settings"], ctx["store"], "inspect", ident=ident,
        operator="isolated-operator", evidence="Inspect isolated erasure receipt")

    assert inspected["retentionReview"]["state"] == "PENDING"
    assert inspected["personalDataState"] == "COMPLETED"
    assert "retentionReview" not in progress(ctx, key, secret).json()
