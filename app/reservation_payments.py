"""Immutable reservation payment policy; legacy bookings remain online bookings."""
from sqlalchemy import select

from app.errors import Problem


PAYPAL = "PAYPAL"
EXTERNAL = "EXTERNAL"


def payment_method(reservation):
    if not reservation:
        return None
    criteria = reservation.get("required_criteria_json") or {}
    method = criteria.get("paymentMethod", PAYPAL) if isinstance(criteria, dict) else PAYPAL
    # Never turn missing/unknown legacy metadata into a payment bypass.
    if method not in (PAYPAL, EXTERNAL):
        raise Problem(409, "RESERVATION_PAYMENT_METHOD_INVALID")
    return method


def checkout_enabled(settings):
    return getattr(settings, "paypal_checkout_enabled", False)


def require_checkout(settings, reservation=None):
    if reservation and payment_method(reservation) == EXTERNAL:
        raise Problem(409, "ONLINE_PAYMENT_NOT_REQUIRED")
    if not checkout_enabled(settings):
        raise Problem(409, "ONLINE_PAYMENT_DISABLED")


def require_no_payment_records(db, session, reservation):
    """An external booking must not silently bypass a real financial record."""
    table = db.table("MSP_RENTAL_PAYMENT")
    if session.execute(select(table.c.payment_id).where(
            table.c.reservation_id == reservation["reservation_id"]).limit(1)).first():
        raise Problem(409, "PAYMENT_STATE_INCONSISTENT")


def paid_booking_payment(payments):
    eligible = [p for p in payments if p["payment_status"] == "PAID" and p["paid_at"] is not None
                and p["paypal_capture_id"] and p["payment_provider"] == PAYPAL
                and p["refunded_amount"] == 0 and p["total_price"] > 0]
    if len(eligible) != 1:
        raise Problem(409, "PAYMENT_REQUIRED" if not eligible else "PAYMENT_STATE_INCONSISTENT")
    payment = eligible[0]
    if payment["rental_contract_id"] is not None:
        raise Problem(409, "PAYMENT_ALREADY_LINKED")
    if any(p["payment_status"] in ("CREATED", "PENDING", "REVERSED", "PARTIALLY_REFUNDED", "REFUNDED")
           or p.get("refund_status", "NONE") not in ("NONE", "NOT_REQUIRED")
           or (p.get("refunded_amount") or 0) > 0
           or (p.get("refund_requested_amount") or 0) > 0 for p in payments):
        raise Problem(409, "PAYMENT_STATE_INCONSISTENT")
    return payment


def payment_flags(settings, reservation):
    method = payment_method(reservation)
    return {"paymentMethod": method,
            "onlinePaymentEnabled": method == PAYPAL and checkout_enabled(settings)}
