"""Reconcile provider reads without impersonating signed webhook deliveries."""
import argparse
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.errors import Problem
from app.paypal import event_client, process_event, save_event


def reconcile_payments(db, client, notifier=None, *, settlement_only=False):
    table = db.table("MSP_RENTAL_PAYMENT")
    conditions = [table.c.payment_environment == client.settings.paypal_environment,
                  table.c.paid_at.is_(None), table.c.paypal_order_id.is_not(None)]
    if settlement_only:
        # A scheduled settlement read must not expire bookings, retry refunds,
        # dispatch pushes, or inspect unattempted checkout orders.
        conditions.extend((table.c.payment_provider == "PAYPAL",
                           table.c.payment_status.in_(("CREATED", "PENDING")),
                           or_(table.c.capture_requested_at.is_not(None), table.c.paypal_capture_id.is_not(None))))
        notifier = None
    else:
        conditions.append(table.c.payment_status.in_(("CREATED", "PENDING", "CANCELED", "FAILED")))
    with db.engine.connect() as connection:
        orders = list(connection.scalars(select(table.c.paypal_order_id).where(
            *conditions).order_by(table.c.payment_id)))
    result = {"checked": 0, "failed": 0}
    if settlement_only:
        result["skipped"] = 0
    for order_id in orders:
        stored = None
        try:
            event = {"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": order_id}}
            snapshot = event_client(db, client, event).snapshot(event)
            capture = snapshot["capture"]
            if settlement_only and (not capture or capture.get("status") != "COMPLETED"):
                result["skipped"] += 1
                continue
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reconcile completed captures using PayPal reads; no charges, refunds, expiry, or push")
    parser.add_argument("--settlement-only", action="store_true", required=True)
    parser.add_argument("--expected-environment", choices=("SANDBOX", "LIVE"))
    parser.add_argument("--expected-database")
    args = parser.parse_args(argv)
    from app.config import Settings
    from app.db import Database
    from app.jobs import _run_locked
    from app.paypal import PayPalClient

    db = client = None
    out = {"job": "payment-settlement-recovery", "at": datetime.now(timezone.utc).isoformat()}
    exit_code = 0
    try:
        settings = Settings()
        if args.expected_environment and settings.paypal_environment != args.expected_environment:
            raise ValueError("unexpected payment environment")
        if not settings.database_url.get_secret_value() or not settings.paypal_client_id.get_secret_value() or not settings.paypal_client_secret.get_secret_value():
            raise ValueError("missing configuration")
        db = Database(settings.database_url.get_secret_value())
        if args.expected_database and db.engine.url.database != args.expected_database:
            raise ValueError("unexpected database")
        client = PayPalClient(settings)
        out["environment"] = settings.paypal_environment
        # Share the existing job lock with the broader payment-maintenance CLI.
        out["result"] = _run_locked(db, "payments", lambda: reconcile_payments(db, client, settlement_only=True))
        out["status"] = "failed" if out["result"]["failed"] else "completed"
        exit_code = 1 if out["result"]["failed"] else 0
    except RuntimeError as error:
        if str(error) == "job is already running: payments":
            out["status"] = "busy"
        else:
            out.update(status="failed", error_code="PAYMENT_RECOVERY_RUNTIME_ERROR")
            exit_code = 1
    except (Problem, SQLAlchemyError, ValueError, TypeError, KeyError) as error:
        out.update(status="failed", error_code=error.code if isinstance(error, Problem) else "PAYMENT_RECOVERY_CONFIGURATION_OR_DATABASE_ERROR")
        exit_code = 1
    finally:
        if client:
            client.close()
        if db:
            db.engine.dispose()
    print(json.dumps(out))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
