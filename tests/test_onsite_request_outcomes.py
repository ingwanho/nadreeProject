from datetime import timedelta
import uuid

import pytest
from sqlalchemy import select

from app.errors import Problem
from app.security import now, sign_user_access
from test_customer_receipt import receipt, external, pending_bookings, new_quote, submit, count, BASE


def result(ctx, key, headers=None):
    return ctx["client"].get(BASE + "/onsite/requests/" + key, headers=headers or ctx["headers"])


def close(ctx, key, headers=None):
    return ctx["client"].post(BASE + "/onsite/requests/" + key + "/close", headers=headers or ctx["headers"])


def recorded(ctx, key):
    table = ctx["db"].table("MSP_RENTAL_ONSITE_REQUEST")
    with ctx["engine"].connect() as conn:
        return dict(conn.execute(select(table).where(table.c.uid_token == "pending-user-0",
            table.c.client_request_id == key)).mappings().one())


def test_404_is_unknown_and_never_closes_request_key(receipt):
    ctx, key = receipt, str(uuid.uuid4())
    missing = result(ctx, key)
    assert missing.status_code == 404
    assert missing.json()["requestStatus"] == "UNKNOWN" and missing.json()["requestFinal"] is False
    assert missing.json()["canStartNewRequest"] is False
    assert count(ctx, "MSP_RENTAL_ONSITE_REQUEST") == 0
    body, quote = new_quote(ctx)
    accepted = submit(ctx, body, quote, key)
    assert accepted.status_code == 200 and accepted.json()["requestStatus"] == "ACCEPTED"
    assert result(ctx, key).json()["item"]["reservationId"] == accepted.json()["item"]["reservationId"]


def test_expired_quote_is_durably_rejected_and_cannot_create_later(receipt, monkeypatch):
    ctx, key = receipt, str(uuid.uuid4())
    body, quote = new_quote(ctx)
    at = now() + timedelta(minutes=11)
    with monkeypatch.context() as patch:
        patch.setattr("app.customer_qr.now", lambda: at)
        failed = submit(ctx, body, quote, key)
    assert failed.status_code == 409 and failed.json()["errorCode"] == "ONSITE_QUOTE_EXPIRED"
    assert failed.json()["requestStatus"] == "REJECTED" and failed.json()["requestFinal"] is True
    assert failed.json()["canStartNewRequest"] is True and failed.json()["retrySameRequest"] is False
    saved = recorded(ctx, key)
    assert saved["request_state"] == "REJECTED" and saved["reservation_id"] is None
    assert body["qrCode"] not in str(saved) and quote["quoteToken"] not in str(saved)
    assert result(ctx, key).status_code == 200 and result(ctx, key).json()["item"] is None
    assert submit(ctx, body, quote, key).json()["requestStatus"] == "REJECTED"
    fresh_body, fresh_quote = new_quote(ctx)
    assert submit(ctx, fresh_body, fresh_quote, key).json()["requestStatus"] == "REJECTED"
    assert count(ctx, "MSP_RESERVATION") == 0
    assert submit(ctx, fresh_body, fresh_quote).json()["requestStatus"] == "ACCEPTED"


def test_close_unknown_key_blocks_delayed_original_submission(receipt):
    ctx, key = receipt, str(uuid.uuid4())
    body, quote = new_quote(ctx)
    assert result(ctx, key).json()["requestStatus"] == "UNKNOWN"
    closed = close(ctx, key)
    assert closed.status_code == 200 and closed.json()["requestStatus"] == "REJECTED"
    assert closed.json()["canStartNewRequest"] is True
    delayed = submit(ctx, body, quote, key)
    assert delayed.status_code == 409 and delayed.json()["errorCode"] == "ONSITE_REQUEST_CLOSED"
    assert close(ctx, key).json() == closed.json()
    assert result(ctx, key).json() == closed.json()
    assert count(ctx, "MSP_RESERVATION") == 0


def test_close_accepted_key_returns_booking_without_canceling_it(receipt):
    ctx, key = receipt, str(uuid.uuid4())
    body, quote = new_quote(ctx)
    accepted = submit(ctx, body, quote, key)
    closed = close(ctx, key)
    assert closed.status_code == 200 and closed.json()["requestStatus"] == "ACCEPTED"
    assert closed.json()["item"]["reservationId"] == accepted.json()["item"]["reservationId"]
    assert closed.json()["item"]["reservationStatus"] == "REQUESTED"
    assert closed.json()["canStartNewRequest"] is False
    assert count(ctx, "MSP_RESERVATION") == 1


def test_processing_is_not_a_final_rejection(receipt, monkeypatch):
    ctx, key = receipt, str(uuid.uuid4())
    body, quote = new_quote(ctx)
    monkeypatch.setattr("app.onsite_requests.try_lock", lambda *args: False)
    monkeypatch.setattr("app.onsite_requests.processing", lambda *args: True)
    for response in (submit(ctx, body, quote, key), result(ctx, key), close(ctx, key)):
        assert response.status_code == 202 and response.headers["Retry-After"] == "2"
        assert response.json()["requestStatus"] == "PROCESSING"
        assert response.json()["requestFinal"] is False and response.json()["item"] is None
        assert response.json()["canStartNewRequest"] is False
    assert count(ctx, "MSP_RENTAL_ONSITE_REQUEST") == 0


def test_failed_attempt_rolls_back_booking_and_retains_recoverable_intent(receipt, monkeypatch):
    from app.customer_qr import _submit_onsite
    ctx, key = receipt, str(uuid.uuid4())
    body, quote = new_quote(ctx)
    def crashed(*args):
        _submit_onsite(*args)
        raise RuntimeError("isolated crash after insert")
    with monkeypatch.context() as patch:
        patch.setattr("app.customer_qr._submit_onsite", crashed)
        with pytest.raises(RuntimeError, match="isolated crash"):
            submit(ctx, body, quote, key)
    assert count(ctx, "MSP_RESERVATION") == 0
    assert recorded(ctx, key)["request_state"] == "PROCESSING"
    unknown = result(ctx, key)
    assert unknown.status_code == 503 and unknown.json()["requestStatus"] == "UNKNOWN"
    assert submit(ctx, body, quote, key).json()["requestStatus"] == "ACCEPTED"
    assert count(ctx, "MSP_RESERVATION") == 1 and recorded(ctx, key)["request_state"] == "ACCEPTED"


def test_business_failure_after_insert_rolls_back_and_closes_key(receipt, monkeypatch):
    from app.customer_qr import _submit_onsite
    ctx, key = receipt, str(uuid.uuid4())
    body, quote = new_quote(ctx)
    def rejected(*args):
        _submit_onsite(*args)
        raise Problem(409, "ISOLATED_FINAL_REJECTION")
    with monkeypatch.context() as patch:
        patch.setattr("app.customer_qr._submit_onsite", rejected)
        failed = submit(ctx, body, quote, key)
    assert failed.status_code == 409 and failed.json()["requestStatus"] == "REJECTED"
    assert count(ctx, "MSP_RESERVATION") == 0
    assert count(ctx, "MSP_RESERVATION_HISTORY") == 0
    assert submit(ctx, body, quote, key).json()["errorCode"] == "ISOLATED_FINAL_REJECTION"


def test_request_outcomes_are_scoped_to_authenticated_customer(receipt):
    ctx, key = receipt, str(uuid.uuid4())
    body, quote = new_quote(ctx)
    other = {"Authorization": "Bearer " + sign_user_access(ctx["settings"], "pending-user-1")}
    assert close(ctx, key, other).json()["requestStatus"] == "REJECTED"
    assert result(ctx, key).json()["requestStatus"] == "UNKNOWN"
    accepted = submit(ctx, body, quote, key)
    assert accepted.json()["requestStatus"] == "ACCEPTED"
    assert result(ctx, key, other).json()["requestStatus"] == "REJECTED"
    assert "reservationId" not in result(ctx, key, other).text


def test_altered_body_does_not_overwrite_accepted_result(receipt):
    ctx, key = receipt, str(uuid.uuid4())
    body, quote = new_quote(ctx)
    accepted = submit(ctx, body, quote, key)
    changed = submit(ctx, {**body, "qrCode": body["qrCode"].upper()}, quote, key)
    assert changed.status_code == 409 and changed.json()["errorCode"] == "REQUEST_KEY_REUSED"
    assert changed.json()["requestStatus"] == "ACCEPTED" and changed.json()["canStartNewRequest"] is False
    assert result(ctx, key).json()["item"]["reservationId"] == accepted.json()["item"]["reservationId"]


def test_previously_accepted_booking_is_not_rejected_when_ledger_is_new(receipt):
    ctx, key = receipt, str(uuid.uuid4())
    body, quote = new_quote(ctx)
    accepted = submit(ctx, body, quote, key)
    table = ctx["db"].table("MSP_RENTAL_ONSITE_REQUEST")
    with ctx["engine"].begin() as conn:
        conn.execute(table.delete().where(table.c.client_request_id == key))
    assert result(ctx, key).json()["requestStatus"] == "ACCEPTED"
    invalid_quote = {**quote, "quoteToken": "invalid-old-token"}
    rejected_body = submit(ctx, body, invalid_quote, key)
    assert rejected_body.status_code == 409 and rejected_body.json()["requestStatus"] == "ACCEPTED"
    assert rejected_body.json()["canStartNewRequest"] is False
    assert close(ctx, key).json()["item"]["reservationId"] == accepted.json()["item"]["reservationId"]
    assert submit(ctx, body, quote, key).json()["item"]["reservationId"] == accepted.json()["item"]["reservationId"]
    assert recorded(ctx, key)["request_state"] == "ACCEPTED"


def test_readiness_requires_request_result_migration(receipt):
    from app.rental_schema import metadata
    ctx = receipt
    metadata.tables["MSP_RENTAL_ONSITE_REQUEST"].drop(ctx["engine"])
    response = ctx["client"].get("/health/ready")
    assert response.status_code == 503 and response.json()["errorCode"] == "ONSITE_REQUEST_SCHEMA_UPDATE_REQUIRED"


@pytest.mark.mysql
def test_mysql_closing_and_submission_cannot_both_win(receipt):
    from test_mysql_concurrency import race
    ctx, key = receipt, str(uuid.uuid4())
    body, quote = new_quote(ctx)
    responses = race(lambda action: submit(ctx, body, quote, key) if action == "submit" else close(ctx, key),
                     ["submit", "close"])
    assert all(r.status_code in (200, 202, 409) for r in responses)
    final = result(ctx, key).json()
    assert final["requestStatus"] in ("ACCEPTED", "REJECTED")
    assert count(ctx, "MSP_RESERVATION") == (1 if final["requestStatus"] == "ACCEPTED" else 0)
