"""Per-handover consent records: ownership, first-write timestamps, and migration."""
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.migrate import migration_plan
from app.security import sign_user_access
from test_external_reservations import external
from test_pending_reservation_approval import pending_bookings
from test_handover_v2 import handover, begin, command, BASE


def consent_row(ctx):
    h = ctx["db"].table("MSP_RENTAL_HANDOVER")
    with ctx["engine"].connect() as connection:
        return dict(connection.execute(select(h).where(h.c.handover_id == ctx["hid"])).mappings().one())


def test_independent_consents_preserve_first_server_times_and_are_visible_in_details(handover, monkeypatch):
    ctx = handover
    begin(ctx)
    initial = consent_row(ctx)
    at = initial["customer_started_at"].replace(microsecond=123456)
    monkeypatch.setattr("app.handover.now", lambda: at)
    notifications = len(ctx["fcm"].notifications)
    first = command(ctx, "/consents", {"privacyPolicyAgreed": True})
    assert first.status_code == 200, first.text
    first_item = first.json()["item"]
    privacy_at = at.replace(microsecond=0).isoformat() + "Z"
    assert first_item["privacyPolicyAgreedAt"] == privacy_at
    assert first_item["termsAgreedAt"] is None
    at += timedelta(seconds=7)
    second = command(ctx, "/consents", {"termsAgreed": True})
    assert second.status_code == 200, second.text
    terms_at = at.replace(microsecond=0).isoformat() + "Z"
    assert second.json()["item"]["privacyPolicyAgreedAt"] == privacy_at
    assert second.json()["item"]["termsAgreedAt"] == terms_at
    before_retry = consent_row(ctx)
    at += timedelta(seconds=7)
    retried = command(ctx, "/consents", {"privacyPolicyAgreed": True, "termsAgreed": True})
    assert retried.status_code == 200, retried.text
    assert consent_row(ctx) == before_retry
    assert len(ctx["fcm"].notifications) == notifications
    assert retried.json()["item"]["signatureStatus"] == "NOT_STARTED"
    assert retried.json()["item"]["signatureCompletedAt"] is None
    for path, headers, nested in [
        (BASE + "/handovers/" + ctx["hid"], ctx["headers"], False),
        ("/nadreego/handovers/" + ctx["hid"], ctx["admin"], False),
        (BASE + "/reservations/" + ctx["rid"], ctx["headers"], True),
    ]:
        response = ctx["client"].get(path, headers=headers)
        assert response.status_code == 200, response.text
        item = response.json()["item"]
        progress = item["handover"] if nested else item
        assert progress["privacyPolicyAgreedAt"] == privacy_at
        assert progress["termsAgreedAt"] == terms_at


def test_both_consents_share_first_timestamp_and_do_not_require_form_or_video(handover):
    ctx = handover
    begin(ctx)
    response = command(ctx, "/consents", {"privacyPolicyAgreed": True, "termsAgreed": True})
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert item["privacyPolicyAgreedAt"] == item["termsAgreedAt"] is not None
    assert item["customerStatus"] == "DRAFT" and item["handoverStatus"] == "IN_PROGRESS"
    assert item["canStartRental"] is False


@pytest.mark.parametrize("body", [{}, {"privacyPolicyAgreed": False}, {"termsAgreed": False},
    {"privacyPolicyAgreed": "true"}, {"termsAgreed": 1}, {"termsAgreed": None},
    {"privacyPolicyAgreed": True, "termsAgreed": False},
    {"termsAgreed": True, "termsAgreedAt": "2020-01-01T00:00:00Z"}])
def test_invalid_consent_does_not_write_any_record(handover, body):
    ctx = handover
    begin(ctx)
    before = consent_row(ctx)
    response = command(ctx, "/consents", body)
    assert response.status_code == 422 and response.json()["errorCode"] == "INVALID_INPUT"
    assert consent_row(ctx) == before


def test_only_owner_can_record_consents(handover):
    ctx = handover
    begin(ctx)
    body = {"privacyPolicyAgreed": True}
    other = {"Authorization": "Bearer " + sign_user_access(ctx["settings"], "pending-user-1")}
    denied = command(ctx, "/consents", body, headers=other)
    assert denied.status_code == 404 and denied.json()["errorCode"] == "HANDOVER_REQUIRED"
    assert command(ctx, "/consents", body, headers=ctx["admin"]).status_code == 401
    path = BASE + "/handovers/" + ctx["hid"] + "/consents"
    assert ctx["client"].post(path, json=body).status_code == 401
    assert consent_row(ctx)["privacy_policy_agreed_at"] is None


@pytest.mark.parametrize("status", ["NOT_STARTED", "CANCELED", "STARTED"])
def test_unstarted_or_closed_handovers_cannot_record_consents(handover, status):
    ctx = handover
    h = ctx["db"].table("MSP_RENTAL_HANDOVER")
    with ctx["engine"].begin() as connection:
        connection.execute(h.update().where(h.c.handover_id == ctx["hid"]).values(handover_status=status))
    response = command(ctx, "/consents", {"privacyPolicyAgreed": True, "termsAgreed": True})
    assert response.status_code == 409 and response.json()["errorCode"] == "HANDOVER_CLOSED"
    assert consent_row(ctx)["privacy_policy_agreed_at"] is None


def test_migration_adds_only_nullable_consent_columns_without_inferred_history(handover):
    ctx = handover
    before = consent_row(ctx)
    with ctx["engine"].begin() as connection:
        for column in ("privacy_policy_agreed_at", "terms_agreed_at"):
            connection.execute(text("ALTER TABLE MSP_RENTAL_HANDOVER DROP COLUMN " + column))
        connection.execute(text("UPDATE MSP_RENTAL_HANDOVER SET signature_status='COMPLETED', "
            "signature_completed_at='2026-11-01 00:00:00'"))
    plan = migration_plan(ctx["db"])
    changes = [(sql, values) for label, sql, values in plan if label in {
        "add MSP_RENTAL_HANDOVER.privacy_policy_agreed_at", "add MSP_RENTAL_HANDOVER.terms_agreed_at"}]
    assert len(changes) == 2 and all("DATETIME DEFAULT NULL" in sql for sql, _ in changes)
    with ctx["engine"].begin() as connection:
        for sql, values in changes:
            connection.execute(text(sql), values)
    after = consent_row(ctx)
    assert after["privacy_policy_agreed_at"] is after["terms_agreed_at"] is None
    assert after["signature_status"] == "COMPLETED" and after["uid_token"] == before["uid_token"]
    assert not any("agreed_at" in label for label, _, _ in migration_plan(ctx["db"]))
