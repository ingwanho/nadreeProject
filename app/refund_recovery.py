"""Durable, bounded refund retries; unknown results never get a fresh key."""
import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import Problem
from app.security import now


def execute_refund(db, client, payment_id, *, manual=False):
    from app.paypal import amount, identifier
    table = db.table("MSP_RENTAL_PAYMENT")
    if "refund_attempt_state" not in table.c:
        raise Problem(503, "PAYMENT_SCHEMA_UPDATE_REQUIRED")
    at = now()
    with Session(db.engine) as session:
        payment = session.execute(select(table).where(table.c.payment_id == payment_id).with_for_update()).mappings().first()
        if not payment or payment["payment_environment"] != client.settings.paypal_environment:
            return False
        if payment["refund_status"] not in ("REQUESTED", "FAILED", "PENDING"):
            return payment["refund_status"] == "COMPLETED"
        target = payment["refund_requested_amount"]
        if target is None or not payment["paypal_capture_id"]:
            return False
        state = dict(payment["refund_attempt_state"] or {})
        if state and not manual and (state.get("manualRequired") or at < datetime.fromisoformat(state["retryAt"])):
            return False
        if not state:
            # Old failed/pending requests have no durable amount/key evidence.
            if payment["refund_status"] != "REQUESTED" or payment["paypal_refund_id"]:
                return False
            if target <= payment["refunded_amount"]:
                session.execute(update(table).where(table.c.payment_id == payment_id).values(
                    refund_status="COMPLETED" if target else "NOT_REQUIRED", updated_at=at))
                session.commit()
                return target > 0
            state = {"requestId": str(uuid.uuid4()), "amount": str(target - payment["refunded_amount"]),
                     "baseRefunded": str(payment["refunded_amount"]), "startedAt": at.isoformat(),
                     "tries": 0, "status": "UNKNOWN", "refundId": None}
        if state.get("status") in ("FAILED", "CANCELLED"):
            # A GET-confirmed failed refund can use a new request identity.
            state = dict(state, requestId=str(uuid.uuid4()), startedAt=at.isoformat(), refundId=None, status="UNKNOWN")
        if not state.get("refundId") and at - datetime.fromisoformat(state["startedAt"]) >= timedelta(days=44):
            state.update(manualRequired=True, lastError="REFUND_IDEMPOTENCY_WINDOW_EXPIRED")
        elif not manual and state["tries"] >= 5:
            state.update(manualRequired=True, lastError="REFUND_RETRIES_EXHAUSTED")
        else:
            state.update(manualRequired=False, tries=state["tries"] + 1,
                         retryAt=(at + timedelta(minutes=min(60, 2 ** state["tries"]))).isoformat())
        session.execute(update(table).where(table.c.payment_id == payment_id).values(
            refund_attempt_state=state, refund_status="FAILED" if state["manualRequired"] else "PENDING", updated_at=at))
        if state["manualRequired"]:
            from app.notifications import payment_notification
            payment_notification(db, session, payment, "REFUND_FAILED", "refund-manual:" + str(payment_id))
        session.commit()
        if state["manualRequired"]:
            return False
        # The checkpoint survives process death; serialize the actual PG request.
        payment = session.execute(select(table).where(table.c.payment_id == payment_id).with_for_update()).mappings().one()
        if payment["refund_attempt_state"] != state or payment["refund_status"] != "PENDING":
            return payment["refund_status"] == "COMPLETED"
        target = payment["refund_requested_amount"]
        try:
            from app.merchant_accounts import payment_client
            seller_client = payment_client(client, payment)
            if state.get("refundId"):
                result = seller_client.get("refunds", state["refundId"])
            else:
                result = seller_client.refund(payment["paypal_capture_id"], state["requestId"],
                                       payment["currency"], Decimal(state["amount"]))
            refund_id = identifier(result["id"])
            if amount(result["amount"]) != (payment["currency"], Decimal(state["amount"])):
                raise Problem(503, "REFUND_AMOUNT_MISMATCH")
            if state.get("refundId") and refund_id != state["refundId"]:
                raise Problem(503, "REFUND_ID_MISMATCH")
            status = result.get("status")
            if status not in ("COMPLETED", "PENDING", "FAILED", "CANCELLED"):
                raise Problem(503, "REFUND_STATUS_UNKNOWN")
            # Confirm failure by a subsequent GET before generating another key.
            confirmed = bool(state.get("refundId"))
            state.update(refundId=refund_id, status=status if confirmed or status in ("COMPLETED", "PENDING") else "PENDING", lastError=None)
        except (Problem, KeyError, TypeError, ValueError) as exc:
            state["lastError"] = exc.code if isinstance(exc, Problem) else "REFUND_RESPONSE_INVALID"
            status = "UNKNOWN"
        values = {"refund_attempt_state": state, "refund_status": "FAILED" if status == "UNKNOWN" else "PENDING", "updated_at": now()}
        if state.get("refundId"):
            values["paypal_refund_id"] = state["refundId"]
        if status == "COMPLETED":
            refunded = max(payment["refunded_amount"], Decimal(state["baseRefunded"]) + Decimal(state["amount"]))
            values.update(refunded_amount=refunded,
                          payment_status="REFUNDED" if refunded == payment["total_price"] else "PARTIALLY_REFUNDED",
                          refund_status="COMPLETED" if refunded >= target else "REQUESTED")
            if refunded < target:
                # The completed amount is reconciled before a supplementary refund.
                values.update(refund_attempt_state=None, paypal_refund_id=None)
        session.execute(update(table).where(table.c.payment_id == payment_id).values(**values))
        session.commit()
        return values["refund_status"] == "COMPLETED"


def retry_refunds(db, client):
    table = db.table("MSP_RENTAL_PAYMENT")
    with db.engine.connect() as connection:
        ids = list(connection.scalars(select(table.c.payment_id).where(
            table.c.payment_environment == client.settings.paypal_environment,
            table.c.refund_status.in_(("REQUESTED", "PENDING", "FAILED")))))
    return sum(execute_refund(db, client, ident) for ident in ids)


def main():
    from app.config import Settings
    from app.db import Database
    from app.paypal import PayPalClient
    parser = argparse.ArgumentParser(description="Inspect/retry one refund; no arbitrary amount or new unknown request key")
    parser.add_argument("payment_id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    db, client = Database(settings.database_url.get_secret_value()), PayPalClient(settings)
    try:
        table = db.table("MSP_RENTAL_PAYMENT")
        with db.engine.connect() as connection:
            row = connection.execute(select(table.c.payment_id, table.c.refund_status, table.c.refund_requested_amount,
                table.c.refunded_amount, table.c.refund_attempt_state).where(table.c.payment_id == args.payment_id,
                table.c.payment_environment == settings.paypal_environment)).mappings().first()
        print(dict(row) if row else "Payment not found in configured environment")
        if args.apply and row:
            print({"completed": execute_refund(db, client, args.payment_id, manual=True)})
    finally:
        client.close()
        if db.engine is not None:
            db.engine.dispose()


if __name__ == "__main__":
    main()
