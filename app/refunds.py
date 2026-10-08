from decimal import Decimal

from sqlalchemy import select, update

from app.errors import Problem
from app.payment_policy import refund_target
from app.security import now


def prepare_booking_refund(request, session, reservation, reason, *, admin_id=None, customer=False):
    table = request.app.state.db.table("MSP_RENTAL_PAYMENT")
    if "refund_requested_amount" not in table.c:
        raise Problem(503, "REFUND_POLICY_SCHEMA_UPDATE_REQUIRED")
    payments = session.execute(select(table).where(
        table.c.reservation_id == reservation["reservation_id"],
        table.c.payment_environment == request.app.state.settings.paypal_environment)
        .order_by(table.c.payment_id).with_for_update()).mappings().all()
    if customer and any(p["payment_status"] == "PENDING" for p in payments):
        raise Problem(409, "PAYMENT_IN_PROGRESS")
    captured = [p for p in payments if p["paid_at"] is not None or
                p["payment_status"] in ("PAID", "PARTIALLY_REFUNDED", "REFUNDED") or
                (p["payment_status"] == "PENDING" and p["paypal_capture_id"])]
    if len(captured) > 1:
        raise Problem(409, "PAYMENT_STATE_INCONSISTENT")
    payment = captured[0] if captured else None
    at = now()
    result = (None, "NOT_REQUIRED", False, Decimal("0.00"), "NO_COMPLETED_PAYMENT")
    if payment:
        status = payment["payment_status"]
        if (payment["payment_provider"] != "PAYPAL" or not payment["paypal_capture_id"] or
                status not in ("PAID", "PARTIALLY_REFUNDED", "REFUNDED", "PENDING")):
            raise Problem(409, "PAYMENT_STATE_INCONSISTENT")
        target = refund_target(payment["total_price"], customer=customer)
        policy = "CUSTOMER_REFUND_90_PERCENT" if customer else "ADMIN_REFUND_100_PERCENT"
        refund_status = payment.get("refund_status", "NONE")
        stored_target = payment.get("refund_requested_amount")
        if refund_status in ("REQUESTED", "PENDING"):
            # Never change the amount of an already submitted PayPal request.
            if stored_target != target:
                raise Problem(409, "REFUND_ALREADY_IN_PROGRESS")
        else:
            refund_status = "COMPLETED" if payment["refunded_amount"] >= target else "REQUESTED"
            session.execute(update(table).where(table.c.payment_id == payment["payment_id"]).values(
                refund_status=refund_status, refund_requested_amount=target,
                refund_requested_at=at, refund_requested_by_admin_id=admin_id,
                refund_reason=reason, updated_at=at))
        result = (payment["payment_id"], refund_status,
                  refund_status == "REQUESTED" and status in ("PAID", "PARTIALLY_REFUNDED"),
                  target, policy)
    for attempt in payments:
        if payment and attempt["payment_id"] == payment["payment_id"]:
            continue
        if attempt["payment_status"] in ("CREATED", "PENDING"):
            session.execute(update(table).where(table.c.payment_id == attempt["payment_id"]).values(
                payment_status="CANCELED", refund_status="NOT_REQUIRED",
                refund_requested_amount=Decimal("0.00"), refund_reason=reason, updated_at=at))
    return result
