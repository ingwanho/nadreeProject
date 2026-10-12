from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.customer_rentals import _ensure_payment_window, _payment_window
from app.errors import Problem
from app.payment_policy import payment_deadline
from app.rental_schema import metadata


def test_deadline_is_earlier_of_first_approval_plus_72_hours_and_start():
    approved = datetime(2026, 10, 12)
    assert payment_deadline(approved, approved + timedelta(days=5)) == approved + timedelta(hours=72)
    assert payment_deadline(approved, approved + timedelta(hours=12)) == approved + timedelta(hours=12)


def test_accepted_quote_does_not_use_live_catalogue(setup):
    from app.customer_rentals import _revalidate_reservation_quote
    from decimal import Decimal
    reservation = {"required_criteria_json": {"quote": {"currency": "USD", "totalOptions": [100, 150], "finalTotal": 100}}}
    result = _revalidate_reservation_quote(SimpleNamespace(app=setup["app"]), None, reservation)
    assert result["finalTotal"] == Decimal("100")


@pytest.mark.parametrize("status", [None, "CREATED", "FAILED", "CANCELED", "PENDING", "REVERSED"])
def test_deadline_blocks_every_unsettled_payment_attempt(setup, monkeypatch, status):
    metadata.create_all(setup["engine"])
    approved = datetime(2026, 10, 12)
    deadline = approved + timedelta(hours=72)
    monkeypatch.setattr("app.customer_rentals.now", lambda: deadline)
    history = metadata.tables["MSP_RESERVATION_HISTORY"]
    with setup["engine"].begin() as conn:
        for at in (approved + timedelta(days=1), approved):
            conn.execute(history.insert().values(reservation_id="deadline", event_type="APPROVED", created_at=at))
    reservation = {"reservation_id": "deadline", "start_datetime": approved + timedelta(days=10),
                   "reservation_status": "APPROVED", "created_at": approved, "updated_at": deadline}
    request = SimpleNamespace(app=setup["app"])
    with Session(setup["engine"]) as session:
        view = _payment_window(request, session, reservation, {"payment_status": status})
        assert view["cannotPayReason"] == "PAYMENT_DEADLINE_EXPIRED"
        assert view["canPay"] is False
        with pytest.raises(Problem) as error:
            _ensure_payment_window(request, session, reservation, {"payment_status": status})
        assert error.value.code == "PAYMENT_DEADLINE_EXPIRED"
