"""Reconcile provider reads without impersonating signed webhook deliveries."""
import hashlib
import json

from sqlalchemy import select, update

from app.errors import Problem
from app.paypal import event_client, process_event, save_event


def reconcile_payments(db, client, notifier=None):
    table = db.table("MSP_RENTAL_PAYMENT")
    with db.engine.connect() as connection:
        orders = list(connection.scalars(select(table.c.paypal_order_id).where(
            table.c.payment_environment == client.settings.paypal_environment,
            table.c.paid_at.is_(None), table.c.paypal_order_id.is_not(None),
            table.c.payment_status.in_(("CREATED", "PENDING", "CANCELED", "FAILED"))).order_by(table.c.payment_id)))
    result = {"checked": 0, "failed": 0}
    for order_id in orders:
        stored = None
        try:
            event = {"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": order_id}}
            snapshot = event_client(db, client, event).snapshot(event)
            capture = snapshot["capture"]
            if capture and capture.get("status") == "COMPLETED":
                event.update(event_type="PAYMENT.CAPTURE.COMPLETED", resource=capture)
            digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()
            event["id"] = "reconcile-" + digest
            stored = save_event(db, client.settings.paypal_environment, event, json.dumps(event), {}, verification_status="API_QUERY")
            process_event(db, client, stored, snapshot, notifier)
            result["checked"] += 1
        except (Problem, KeyError, TypeError, ValueError) as exc:
            # No provider evidence means no expiration or new charge authorization.
            result["failed"] += 1
            if stored:
                events = db.table("MSP_PAYPAL_WEBHOOK_EVENT")
                with db.engine.begin() as connection:
                    connection.execute(update(events).where(events.c.webhook_event_id == stored["webhook_event_id"],
                        events.c.processing_status.not_in(("PROCESSED", "IGNORED"))).values(
                        processing_status="FAILED", last_error=exc.code if isinstance(exc, Problem) else "PAYPAL_RESPONSE_INVALID"))
    return result
