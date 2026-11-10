from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
import secrets

import pytest
from sqlalchemy import select, update

from account_deletion_helpers import MemoryDeletionStore, PrivacyChatStore
from app.account_deletion_jobs import run
from app.account_deletion_store import TERMINAL, digest, utc
from app.chat import admin_uid
from app.rental_schema import metadata
from app.security import GENERAL, PRIMARY
from test_pending_reservation_approval import pending_bookings

BASE = "/nadreego/admin/account-deletion-requests"


@pytest.fixture
def privacy(setup):
    metadata.create_all(setup["engine"])
    store, chats, deleted, notices, revoked = MemoryDeletionStore(), PrivacyChatStore(), [], [], []
    store.rows["policy_retention"] = {"verified": True, "activeStoresReviewed": True, "reviewUntil": utc() + timedelta(days=30),
        "logMaxDays": 30, "backupMaxDays": 30, "verifiedBy": "isolated-operator"}
    chat = SimpleNamespace(store=lambda: chats, revoke=lambda uid: revoked.append(uid),
        delete_admin_identity=lambda ident: deleted.append(admin_uid(ident)) or True)
    mailer = SimpleNamespace(send_deletion_notice=lambda email, ident, completed=False: notices.append((email, ident, completed)))
    setup["app"].state.deletions = store
    setup["app"].state.chat = chat
    return {**setup, "store": store, "chats": chats, "chat": chat, "mailer": mailer,
            "deleted": deleted, "notices": notices, "revoked": revoked}


def submit(ctx, headers, *, key=None, secret=None, token=None):
    key, secret = key or str(uuid4()), secret or secrets.token_urlsafe(32)
    if token is None:
        context = ctx["client"].get("/nadreego/admin/account-deletion-context", headers=headers)
        assert context.status_code == 200, context.text
        token = context.json()["confirmationToken"]
    body = {"confirmationToken": token, "confirmed": True}
    sent = {**headers, "Idempotency-Key": key, "Deletion-Receipt-Token": secret}
    response = ctx["client"].post(BASE, headers=sent, json=body)
    return response, key, secret, body


def progress(ctx, key, secret):
    return ctx["client"].get(BASE + "/status", headers={"Idempotency-Key": key,
        "Authorization": "DeletionReceipt " + secret})


def process(ctx, at=None):
    return run(ctx["db"], ctx["settings"], ctx["store"], ctx["chat"], ctx["mailer"], at=at)


def register_pending_self(ctx):
    """Keep batch-only SELF coverage separate from immediate app withdrawal."""
    from app.account_deletion_ops import act
    key, secret = str(uuid4()), secrets.token_urlsafe(32)
    accepted = act(ctx["db"], ctx["settings"], ctx["store"], "register", admin_id="general",
        email="general@example.com", idempotency=key, receipt=secret,
        operator="isolated", evidence="isolated")
    return accepted, key, secret


def test_general_single_request_reaches_erasure_notification_and_receipt_after_logout(privacy, signin):
    ctx = privacy
    own, primary = signin("general"), signin()
    accepted, key, secret, body = submit(ctx, own)
    assert accepted.status_code == 202, accepted.text
    data = accepted.json()
    assert data["requestAccepted"] is True and "deleted" not in data
    assert data["scope"] == "SELF" and data["requestState"] == "PROCESSING"
    assert data["accessState"] == "REVOKED" and data["personalDataState"] == "IN_PROGRESS"
    assert data["affectedAdminCount"] == 1 and data["affectedShopCount"] == 0
    assert ctx["deleted"] == [] and ctx["notices"] == []
    assert ctx["store"].get(data["requestId"])["steps"]["withdrawal"] is True
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    blocked = ctx["client"].post("/nadreego/admin/update", headers=own, json={"name": "changed after confirmation"})
    assert blocked.status_code == 401
    due = ctx["store"].get(data["requestId"])["processingDueAt"]
    assert process(ctx)["completed"] == 1
    completed = progress(ctx, key, secret)
    assert completed.status_code == 200
    assert completed.json()["requestState"] == "COMPLETED"
    assert completed.json()["accessState"] == "REVOKED"
    assert ctx["store"].get(data["requestId"])["processingDueAt"] == due
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    assert ctx["client"].get("/nadreego/shop/admin", headers=primary).status_code == 200
    account = ctx["db"].table("MSP_ADMIN")
    with ctx["engine"].connect() as connection:
        erased = connection.execute(select(account).where(account.c.admin_id == "general")).mappings().one()
    assert erased["admin_name"] is None and erased["email"] is None and erased["phone"] is None
    assert erased["is_active"] == 0 and erased["login_id"] != "general@example.com"
    assert ctx["deleted"] == [admin_uid("general")]
    assert len(ctx["notices"]) == 2 and ctx["notices"][-1][2] is True
    private = ctx["store"].get(data["requestId"])
    assert "ownerId" not in private and "snapshot" not in private and "privateContacts" not in private
    assert "general@example.com" not in repr(private)
    retry = ctx["client"].post(BASE, headers={**own, "Idempotency-Key": key, "Deletion-Receipt-Token": secret}, json=body)
    assert retry.status_code == 202 and retry.json()["requestId"] == data["requestId"]
    assert len(ctx["notices"]) == 2


def test_same_key_payload_reuse_and_wrong_receipt_do_not_expose_or_duplicate_work(privacy, signin):
    ctx = privacy
    own = signin("general")
    accepted, key, secret, body = submit(ctx, own)
    assert accepted.status_code == 202
    revoked = list(ctx["revoked"])
    saved = ctx["store"].get(accepted.json()["requestId"])
    repeat, _, _, _ = submit(ctx, own, key=key, secret=secret, token=body["confirmationToken"])
    assert repeat.status_code == 202 and repeat.json()["requestId"] == accepted.json()["requestId"]
    assert ctx["revoked"] == revoked and ctx["store"].get(saved["requestId"]) == saved
    changed, _, _, _ = submit(ctx, own, key=key, secret=secret, token=body["confirmationToken"] + "x")
    assert changed.status_code == 409 and changed.json()["errorCode"] == "IDEMPOTENCY_KEY_REUSED"
    assert progress(ctx, key, secrets.token_urlsafe(32)).status_code == 404
    assert ctx["client"].get("/nadreego/admin/account-deletion-context", headers=own).status_code == 401
    duplicate = ctx["client"].post(BASE, headers={**own, "Idempotency-Key": str(uuid4()),
        "Deletion-Receipt-Token": secrets.token_urlsafe(32)}, json=body)
    assert duplicate.status_code == 401
    assert len(list(ctx["store"].pending())) == 1


def test_confirmation_is_bound_to_actor_role_and_current_subtree(privacy, signin):
    ctx = privacy
    primary, general = signin(), signin("general")
    token = ctx["client"].get("/nadreego/admin/account-deletion-context", headers=general).json()["confirmationToken"]
    forged, _, _, _ = submit(ctx, primary, token=token)
    assert forged.status_code == 422 and forged.json()["errorCode"] == "INVALID_CONFIRMATION"
    fresh = ctx["client"].get("/nadreego/admin/account-deletion-context", headers=primary).json()["confirmationToken"]
    assert ctx["client"].post("/nadreego/admin/roleChange", headers=primary, json={"adminId": "general"}).status_code == 200
    changed, _, _, _ = submit(ctx, primary, token=fresh)
    assert changed.status_code == 409 and changed.json()["errorCode"] == "DELETION_SCOPE_CHANGED"
    assert not list(ctx["store"].pending())


def test_primary_waits_for_all_work_and_can_reject_but_cannot_accept_new_work(privacy, signin, pending_bookings):
    ctx = privacy
    _, request_booking = pending_bookings
    reservation = request_booking(0)["reservationId"]
    primary = signin()
    response, key, secret, _ = submit(ctx, primary)
    assert response.status_code == 202, response.text
    data = response.json()
    assert data["requestState"] == "WAITING_OBLIGATIONS"
    assert data["processingDueAt"] is None and data["accessState"] == "LIMITED_TO_SETTLEMENT"
    assert process(ctx)["completed"] == 0
    assert ctx["client"].get("/nadreego/shop/admin", headers=primary).status_code == 200
    failed = request_booking(1, expected=409)
    assert failed["errorCode"] == "SHOP_CLOSING"
    new = ctx["client"].post("/api/v1/organizations/spots", headers=primary,
        json={"spot_name": "blocked", "unit_type": "region", "parent_spot_id": "root"})
    assert new.status_code == 409 and new.json()["errorCode"] == "SHOP_CLOSING"
    assert ctx["client"].delete("/nadreego/admin/account", headers=primary).status_code == 409
    rejected = ctx["client"].post("/nadreego/booking/action", headers=primary,
        json={"bookedNo": "BO" + reservation, "action": "REJECT"})
    assert rejected.status_code == 200, rejected.text
    assert process(ctx)["completed"] == 0
    row = ctx["store"].get(data["requestId"])
    assert row["accessState"] == "REVOKED" and row["requestState"] == "ACTION_REQUIRED"
    assert row["eligibleAt"] is not None and row["processingDueAt"] is not None
    # Operator verifies remaining shared location/contract copies in this same request.
    ctx["store"].update(row["requestId"], {"dataReviewConfirmedHash": row["scopeHash"]})
    assert process(ctx)["completed"] == 1
    assert progress(ctx, key, secret).json()["requestState"] in TERMINAL


def test_other_service_profile_and_role_are_retained_with_explicit_reason(privacy, signin):
    ctx = privacy
    mapping = ctx["db"].table("MSP_ADMIN_ROLE")
    with ctx["engine"].begin() as connection:
        connection.execute(mapping.insert().values(admin_id="general", role_code="viewer"))
    response, key, secret, _ = submit(ctx, signin("general"))
    assert response.status_code == 202
    assert process(ctx)["completed"] == 1
    state = progress(ctx, key, secret).json()
    assert state["requestState"] == "COMPLETED_WITH_RETENTION"
    assert state["retainedData"][0]["retentionBasis"] == "OTHER_ACTIVE_SERVICE_RELATIONSHIP"
    admins = ctx["db"].table("MSP_ADMIN")
    with ctx["engine"].connect() as connection:
        account = connection.execute(select(admins).where(admins.c.admin_id == "general")).mappings().one()
        remaining = set(connection.scalars(select(mapping.c.role_code).where(mapping.c.admin_id == "general")))
    assert account["email"] == "general@example.com" and account["is_active"] == 1
    assert remaining == {"viewer"}


def test_owned_chat_is_redacted_and_other_party_mentions_require_review(privacy, signin):
    ctx = privacy
    chats = ctx["chats"]
    chats.ref("chatRoomAccess/room").set({"customerUid": "customer", "shopId": "root", "lastSequence": 2})
    chats.ref("chatRoomAccess/room/messages/own").set({"senderUid": admin_uid("general"), "text": "private employee text",
        "sequence": 1, "createdAt": utc()})
    chats.ref("chatRoomAccess/room/messages/customer").set({"senderUid": "customer", "text": "Hello general@example.com",
        "sequence": 2, "createdAt": utc()})
    response, _, _, _ = submit(ctx, signin("general"))
    process(ctx)
    own = chats.ref("chatRoomAccess/room/messages/own").get().to_dict()
    assert own["senderUid"] == "deleted-admin" and own["text"] == "[Deleted]" and own["sequence"] == 1
    other = chats.ref("chatRoomAccess/room/messages/customer").get().to_dict()
    assert other["text"] == "Hello general@example.com"
    row = ctx["store"].get(response.json()["requestId"])
    assert row["requestState"] == "ACTION_REQUIRED" and "OTHER_PARTY_CHAT_MENTIONS" in row["reviewRequired"]


def test_partial_external_failure_is_saved_and_retries_without_extending_deadline(privacy, signin):
    ctx = privacy
    own = signin("general")
    calls = []

    def fail(uid):
        calls.append(uid)
        raise RuntimeError("private provider detail must not enter the response")

    ctx["chat"].revoke = fail
    response, key, secret, _ = submit(ctx, own)
    assert response.status_code == 503 and response.json()["errorCode"] == "DELETION_OUTCOME_UNKNOWN"
    before = ctx["store"].active("general")
    ident = before["requestId"]
    waiting = ctx["store"].get(ident)
    assert waiting["phase"] == "WITHDRAWING" and not waiting["steps"].get("withdrawal")
    assert "private provider" not in response.text + progress(ctx, key, secret).text
    ctx["chat"].revoke = lambda uid: None
    assert process(ctx, at=utc() + timedelta(minutes=5))["completed"] == 1
    assert ctx["store"].get(ident)["processingDueAt"] == before["processingDueAt"]
    assert len(calls) == 1


def test_receipt_expires_only_thirty_days_after_completion_pending_requests_survive(privacy, signin):
    ctx = privacy
    accepted, _, _, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]
    assert ctx["store"].remove_expired(utc() + timedelta(days=100)) == 0
    process(ctx)
    row = ctx["store"].get(ident)
    assert row["receiptExpiresAt"] - row["completedAt"] == timedelta(days=30)
    assert ctx["store"].remove_expired(utc(row["completedAt"]) + timedelta(days=29)) == 0
    assert ctx["store"].remove_expired(utc(row["completedAt"]) + timedelta(days=30)) == 1


def test_missing_copies_policy_does_not_block_completed_active_system_erasure(privacy, signin):
    ctx = privacy
    ctx["store"].rows.pop("policy_retention")
    accepted, key, secret, _ = submit(ctx, signin("general"))
    result = process(ctx)
    assert result["completed"] == 1 and result["deferred"] == 0
    status = progress(ctx, key, secret).json()
    assert status["requestState"] == "COMPLETED" and status["personalDataState"] == "COMPLETED"
    assert status["completedAt"] is not None and status["completionScope"] == "COMPANY_ACTIVE_SYSTEMS"
    row = ctx["store"].get(accepted.json()["requestId"])
    assert row["retentionReview"]["state"] == "PENDING"
    for item in status["residualCopies"]:
        if item["category"] in ("COMPANY_RESTRICTED_BACKUP", "COMPANY_LOG_RETENTION"):
            assert item["reviewState"] == "PENDING" and item["requestedMaxDays"] == 30
            assert "deleteBy" not in item


def test_scope_drift_waits_for_fresh_confirmation_without_resetting_request(privacy, signin, pending_bookings):
    ctx = privacy
    _, request_booking = pending_bookings
    reservation = request_booking(0)["reservationId"]
    own = signin()
    accepted, key, secret, _ = submit(ctx, own)
    ident = accepted.json()["requestId"]
    original = ctx["store"].get(ident)
    ctx["revoked"].clear()
    # Simulates a scope change by another authorized service while this request waits.
    admins = ctx["db"].table("MSP_ADMIN")
    with ctx["engine"].begin() as conn:
        conn.execute(update(admins).where(admins.c.admin_id == "general").values(primary_spot_master_id=None))
    process(ctx)
    assert progress(ctx, key, secret).json()["requestState"] == "WAITING_RECONFIRMATION"
    assert not ctx["revoked"]
    context = ctx["client"].get("/nadreego/admin/account-deletion-context", headers=own).json()
    payload = {"confirmationToken": context["confirmationToken"], "confirmed": True}
    reconfirm = ctx["client"].post(BASE + "/" + ident + "/reconfirm",
        headers={**own, "Deletion-Receipt-Token": secret}, json=payload)
    assert reconfirm.status_code == 202, reconfirm.text
    assert reconfirm.json()["affectedAdminCount"] == len(original["snapshot"]["admins"]) - 1
    assert reconfirm.json()["receivedAt"] == accepted.json()["receivedAt"]
    repeat = ctx["client"].post(BASE + "/" + ident + "/reconfirm",
        headers={"Deletion-Receipt-Token": secret}, json=payload)
    assert repeat.status_code == 202
    assert ctx["store"].get(ident)["processingDueAt"] == original["processingDueAt"]


def test_committed_withdrawal_is_recovered_after_checkpoint_failure(privacy, signin):
    ctx = privacy
    own = signin("general")
    update_record = ctx["store"].update
    failed = []

    def checkpoint_failure(ident, values):
        if values.get("phase") == "ERASING" and not failed:
            failed.append(True)
            raise RuntimeError("Firestore checkpoint unavailable after SQL commit")
        update_record(ident, values)

    ctx["store"].update = checkpoint_failure
    response, key, secret, _ = submit(ctx, own)
    assert response.status_code == 503 and response.json()["errorCode"] == "DELETION_OUTCOME_UNKNOWN"
    saved = ctx["store"].active("general")
    ident = saved["requestId"]
    assert saved["phase"] == "WITHDRAWING" and not saved["steps"].get("withdrawal")
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 401
    assert process(ctx, at=utc() + timedelta(minutes=5))["completed"] == 1
    assert progress(ctx, key, secret).json()["requestState"] == "COMPLETED"
    assert ctx["store"].get(ident)["processingDueAt"] == saved["processingDueAt"]
    assert failed == [True]


def test_operator_recovery_rotation_and_email_intake_share_the_original_job(privacy, signin):
    from app.account_deletion_ops import act
    from app.errors import Problem
    ctx = privacy
    accepted, key, secret, _ = submit(ctx, signin("general"))
    ident = accepted.json()["requestId"]
    common = dict(operator="isolated-test", evidence="verified registered email outside this test")
    process(ctx)
    lookup = act(ctx["db"], ctx["settings"], ctx["store"], "lookup", email="general@example.com", **common)
    assert lookup["items"][0]["requestId"] == ident
    new_secret = secrets.token_urlsafe(32)
    act(ctx["db"], ctx["settings"], ctx["store"], "rotate-receipt", ident=ident,
        email="general@example.com", receipt=new_secret, **common)
    assert progress(ctx, key, secret).status_code == 404
    assert progress(ctx, key, new_secret).status_code == 200
    assert act(ctx["db"], ctx["settings"], ctx["store"], "lookup", email="someone@example.com", **common) == {"items": []}
    with pytest.raises(Problem):
        act(ctx["db"], ctx["settings"], ctx["store"], "rotate-receipt", ident=ident,
            email="someone@example.com", receipt=new_secret, **common)
    created = act(ctx["db"], ctx["settings"], ctx["store"], "register", admin_id="primary",
        email="primary@example.com", idempotency=str(uuid4()), receipt=secrets.token_urlsafe(32), **common)
    duplicate = act(ctx["db"], ctx["settings"], ctx["store"], "register", admin_id="primary",
        email="primary@example.com", idempotency=str(uuid4()), receipt=secrets.token_urlsafe(32), **common)
    assert created["requestId"] == duplicate["requestId"]


def test_operator_shared_data_review_remains_required_without_copies_policy(privacy, signin):
    from app.account_deletion_ops import act
    ctx = privacy
    ctx["store"].rows.pop("policy_retention")
    accepted, key, secret, _ = submit(ctx, signin())
    ident = accepted.json()["requestId"]
    process(ctx)
    due = ctx["store"].get(ident)["processingDueAt"]
    common = dict(operator="isolated-test", evidence="review completed against disposable data")
    with pytest.raises(ValueError, match="every reported category"):
        act(ctx["db"], ctx["settings"], ctx["store"], "review", ident=ident, report={}, **common)
    categories = ctx["store"].get(ident)["reviewRequired"]
    act(ctx["db"], ctx["settings"], ctx["store"], "review", ident=ident,
        report={"reviewedCategories": categories, "retainedData": []}, **common)
    assert process(ctx)["completed"] == 1
    state = progress(ctx, key, secret).json()
    assert ctx["store"].get(ident)["processingDueAt"] == due
    assert state["requestState"] == "COMPLETED" and state["personalDataState"] == "COMPLETED"
    assert ctx["store"].get(ident)["retentionReview"]["state"] == "PENDING"
    for item in state["residualCopies"]:
        if item["category"] in ("COMPANY_RESTRICTED_BACKUP", "COMPANY_LOG_RETENTION"):
            assert item["reviewState"] == "PENDING" and "deleteBy" not in item


def test_no_firebase_identity_does_not_claim_provider_deletion(privacy, signin):
    ctx = privacy
    ctx["chat"].delete_admin_identity = lambda ident: False
    accepted, key, secret, _ = submit(ctx, signin("general"))
    assert process(ctx)["completed"] == 1
    assert all(item["category"] != "FIREBASE_AUTH_PROVIDER_RESIDUAL" for item in progress(ctx, key, secret).json()["residualCopies"])


def test_repeated_failure_requires_operator_and_never_extends_seven_days(privacy, signin):
    from app.account_deletion_ops import act
    ctx = privacy
    accepted, key, secret = register_pending_self(ctx)
    ident = accepted["requestId"]
    original = ctx["store"].get(ident)
    ctx["chat"].revoke = lambda uid: (_ for _ in ()).throw(RuntimeError("isolated provider failure"))
    for minute in (0, 5, 15, 35, 95):
        process(ctx, at=utc() + timedelta(minutes=minute))
    row = ctx["store"].get(ident)
    assert row["requestState"] == "ACTION_REQUIRED" and row["attempts"] == 5
    ctx["chat"].revoke = lambda uid: None
    assert process(ctx, at=utc() + timedelta(hours=3))["completed"] == 0
    act(ctx["db"], ctx["settings"], ctx["store"], "resume", ident=ident,
        operator="isolated-test", evidence="provider recovered")
    assert process(ctx, at=utc() + timedelta(hours=3))["completed"] == 1
    assert ctx["store"].get(ident)["processingDueAt"] == original["processingDueAt"]


def test_receipt_grants_no_regular_login_or_other_request_access(privacy, signin):
    ctx = privacy
    accepted, key, secret, _ = submit(ctx, signin("general"))
    other, other_key, other_secret, _ = submit(ctx, signin())
    assert progress(ctx, other_key, secret).status_code == 404
    assert progress(ctx, key, other_secret).status_code == 404
    assert ctx["client"].get("/nadreego/shop/admin", headers={"Authorization": "DeletionReceipt " + secret}).status_code == 401
    assert secret not in accepted.text and "general@example.com" not in accepted.text
    document = ctx["client"].get("/openapi.json").json()
    assert document["paths"][BASE + "/status"]["get"]["security"] == [{"DeletionReceipt": []}]
    assert "COMPLETED_WITH_RETENTION" in document["components"]["schemas"]["AccountDeletionRequestResult"]["properties"]["requestState"]["enum"]


def test_actual_walkin_return_still_needs_external_settlement_confirmation(privacy, signin):
    from app.account_deletion_ops import act
    from app.errors import Problem
    from app.security import now
    ctx = privacy
    contracts = ctx["db"].table("MSP_RENTAL_CONTRACT")
    at = now()
    with ctx["engine"].begin() as conn:
        conn.execute(contracts.insert().values(rental_contract_id="walkin-obligation", reservation_id=None,
            vehicle_id="isolated-vehicle", uid_token="isolated-customer", pickup_spot_master_id="root",
            actual_start_time=at - timedelta(days=2), planned_end_date=(at - timedelta(days=1)).date(),
            contract_status="OVERDUE", created_at=at, updated_at=at))
    accepted, key, secret, _ = submit(ctx, signin())
    ident = accepted.json()["requestId"]
    assert accepted.json()["outstandingWork"]["activeRentals"] == 1
    assert accepted.json()["outstandingWork"]["pendingExternalSettlements"] == 1
    common = dict(operator="isolated-test", evidence="external receipt verified", ident=ident)
    with pytest.raises(Problem) as error:
        act(ctx["db"], ctx["settings"], ctx["store"], "settlement", **common)
    assert error.value.code == "OBLIGATIONS_NOT_SETTLED"
    with ctx["engine"].begin() as conn:
        conn.execute(update(contracts).values(contract_status="RETURNED", actual_end_time=at))
    process(ctx)
    assert progress(ctx, key, secret).json()["processingDueAt"] is None
    act(ctx["db"], ctx["settings"], ctx["store"], "settlement", **common)
    ready = ctx["store"].get(ident)
    assert ready["processingDueAt"] - ready["eligibleAt"] == timedelta(days=7)
    process(ctx)
    assert ctx["store"].get(ident)["accessState"] == "REVOKED"


def test_commit_response_loss_remains_one_saved_request_and_not_false_rejection(privacy, signin):
    ctx = privacy
    create = ctx["store"].create

    def lost_response(row):
        create(row)
        raise RuntimeError("simulated commit acknowledgement lost")

    ctx["store"].create = lost_response
    response, key, secret, body = submit(ctx, signin("general"))
    assert response.status_code == 503 and response.json()["errorCode"] == "DELETION_OUTCOME_UNKNOWN"
    assert "requestAccepted" not in response.json()
    assert progress(ctx, key, secret).status_code == 200
    assert len(list(ctx["store"].pending())) == 1
    ctx["store"].create = create
    retry = ctx["client"].post(BASE, headers={"Idempotency-Key": key, "Deletion-Receipt-Token": secret}, json=body)
    assert retry.status_code == 202
    assert process(ctx)["completed"] == 1


def test_missing_notification_contact_is_skipped_without_blocking_deletion(privacy, signin):
    ctx = privacy
    account = ctx["db"].table("MSP_ADMIN")
    with ctx["engine"].begin() as conn:
        conn.execute(update(account).where(account.c.admin_id == "general").values(email=None))
    accepted, key, secret, _ = submit(ctx, signin("general"))
    assert accepted.status_code == 202
    result = process(ctx)
    assert result["deferred"] == 0 and result["completed"] == 1
    row = ctx["store"].get(accepted.json()["requestId"])
    assert row["requestState"] == "COMPLETED"
    for stage in ("received", "completed"):
        summary = row["notificationResults"][stage]
        assert summary["sentCount"] == 0 and summary["failedCount"] == 0 and summary["skippedCount"] == 1
        assert summary["errorCodes"] == ["DELETION_NOTIFICATION_CONTACT_REQUIRED"]
    assert progress(ctx, key, secret).json()["completedAt"] is not None
    assert ctx["deleted"] == [admin_uid("general")] and not ctx["notices"]


@pytest.mark.mysql
def test_mysql_reservation_racing_with_primary_deletion_is_blocked_or_included(privacy, signin, pending_bookings):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    ctx = privacy
    _, booking = pending_bookings
    own = signin()
    token = ctx["client"].get("/nadreego/admin/account-deletion-context", headers=own).json()["confirmationToken"]
    barrier = Barrier(2)

    def accept():
        barrier.wait(timeout=10)
        return submit(ctx, own, token=token)[0]

    def reserve():
        barrier.wait(timeout=10)
        # Both outcomes are valid: a committed booking must be counted; a later
        # booking must be refused by the admission marker under the same spot lock.
        from datetime import date
        from app.security import sign_user_access
        start = date.today() + timedelta(days=7)
        return ctx["client"].post("/api/v1/nadree/rental/request", headers={
            "Authorization": "Bearer " + sign_user_access(ctx["settings"], "pending-user-0")},
            json={"spotMasterId": "root", "modelId": "pending-model", "startDate": str(start),
                  "returnDate": str(start + timedelta(days=3)), "totalPrice": 30,
                  "currency": "USD", "deliveryRequested": False})

    with ThreadPoolExecutor(max_workers=2) as workers:
        deletion = workers.submit(accept)
        reservation = workers.submit(reserve)
        accepted, booked = deletion.result(timeout=30), reservation.result(timeout=30)
    assert accepted.status_code == 202, accepted.text
    assert booked.status_code in (200, 409), booked.text
    process(ctx)
    row = ctx["store"].get(accepted.json()["requestId"])
    if booked.status_code == 200:
        assert row["requestState"] == "WAITING_OBLIGATIONS" and row["outstandingWork"]["pendingReservations"] == 1
        assert row["accessState"] == "LIMITED_TO_SETTLEMENT"
    else:
        assert booked.json()["errorCode"] == "SHOP_CLOSING"
