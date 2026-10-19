"""Fail-closed checks before creating another order or capturing money."""
from datetime import timedelta

from sqlalchemy import select

from app.errors import Problem
from app.security import now
from app.merchant_accounts import payment_client

SETTLED = ("PAID", "PARTIALLY_REFUNDED", "REFUNDED")
# Stay below the default six-hour Orders idempotency retention window.
SAFE_REPLAY_WINDOW = timedelta(hours=5)


def attempts(db, session, reservation_id, environment):
    table = db.table("MSP_RENTAL_PAYMENT")
    if not {"order_requested_at", "capture_requested_at", "refund_attempt_state"}.issubset(table.c.keys()):
        raise Problem(503, "PAYMENT_SCHEMA_UPDATE_REQUIRED")
    return [dict(row) for row in session.execute(select(table).where(
        table.c.reservation_id == reservation_id, table.c.payment_environment == environment)
        .order_by(table.c.payment_id).with_for_update()).mappings()]


def guard_other_attempts(rows, current_id=None, client=None):
    others = [row for row in rows if row["payment_id"] != current_id]
    paid = next((row for row in others if row["payment_status"] in SETTLED or row.get("paid_at")), None)
    if paid:
        raise Problem(409, "PAYMENT_ALREADY_PAID", payment_id=paid["payment_id"])
    for row in others:
        if row["payment_status"] not in ("FAILED", "CANCELED") or not confirmed_unpaid(client, row, terminal=True):
            raise Problem(409, "PAYMENT_IN_PROGRESS", payment_id=row["payment_id"])


def confirmed_unpaid(client, payment, *, terminal=False):
    """A transport error is never proof of non-payment."""
    if payment.get("paypal_capture_id"):
        if client is None:
            return False
        capture = payment_client(client, payment).get("captures", payment["paypal_capture_id"])
        return capture.get("id") == payment["paypal_capture_id"] and capture.get("status") in ("DECLINED", "DENIED", "FAILED")
    if payment.get("paypal_order_id"):
        if client is None:
            return False
        order = inspect_order(client, payment)
        return order["status"] in ("VOIDED", "EXPIRED", "CANCELED") or (not terminal and not payment.get("capture_requested_at"))
    return not payment.get("order_requested_at") and not payment.get("capture_requested_at") and payment["payment_status"] != "PENDING"


def replay_allowed(started):
    if started and now() - started >= SAFE_REPLAY_WINDOW:
        raise Problem(409, "PAYMENT_RECONCILIATION_REQUIRED")


def inspect_order(client, payment):
    order = payment_client(client, payment).get("orders", payment["paypal_order_id"])
    if not isinstance(order, dict) or order.get("id") != payment["paypal_order_id"]:
        raise Problem(409, "PAYMENT_RECONCILIATION_REQUIRED", payment_id=payment["payment_id"])
    units = order.get("purchase_units", [])
    if len(units) != 1 or units[0].get("payee", {}).get("merchant_id") != payment["paypal_merchant_id"]:
        raise Problem(409, "PAYPAL_MERCHANT_MISMATCH")
    captures = [capture for unit in order.get("purchase_units", [])
                for capture in unit.get("payments", {}).get("captures", [])]
    if captures or order.get("status") == "COMPLETED":
        # Even a denied/partial capture must be reconciled before another charge.
        raise Problem(409, "PAYMENT_IN_PROGRESS", payment_id=payment["payment_id"])
    if order.get("status") not in ("CREATED", "SAVED", "PAYER_ACTION_REQUIRED", "APPROVED", "VOIDED", "EXPIRED", "CANCELED"):
        raise Problem(409, "PAYMENT_RECONCILIATION_REQUIRED", payment_id=payment["payment_id"])
    return order
