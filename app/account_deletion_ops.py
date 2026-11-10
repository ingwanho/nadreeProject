"""Local operator actions for an already verified deletion request. No public admin backdoor."""
import argparse
import hashlib
import hmac
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.account_deletion_scope import capture, outstanding, pending_scope_allowed
from app.account_deletion_security import email_hash, validate_keys
from app.account_deletion_store import DeletionStore, TERMINAL, body_digest, digest, request_id, utc
from app.account_deletions import make_record, public
from app.config import Settings
from app.db import Database
from app.errors import Problem
from app.security import Principal


def private_text(path):
    file = Path(path)
    if file.stat().st_mode & 0o077:
        raise ValueError("Use an owner-only 0600 input file")
    return file.read_text().strip()


def verified_owner(settings, row, email):
    if not row or not hmac.compare_digest(row.get("ownerEmailHash", ""), email_hash(settings, email)):
        raise Problem(404, "DELETION_REQUEST_UNAVAILABLE")
    if row.get("expiresAt") and utc(row["expiresAt"]) <= utc():
        raise Problem(404, "DELETION_REQUEST_UNAVAILABLE")


def act(db, settings, store, command, *, operator, evidence, ident=None, email=None, receipt=None,
        admin_id=None, idempotency=None, report=None, log_days=30, backup_days=30):
    at = utc()
    if not operator.strip() or not evidence.strip():
        raise ValueError("Operator identity and verification evidence are required")
    audit = {"operator": operator, "evidenceHash": hashlib.sha256(evidence.encode()).hexdigest(), "at": at}
    if command == "policy":
        if not 0 <= log_days <= 30 or not 0 <= backup_days <= 30:
            raise ValueError("Log and restricted-backup controls must be verified within 0..30 days")
        store.put("policy_retention", {"verified": True, "activeStoresReviewed": True,
            "logMaxDays": log_days, "backupMaxDays": backup_days,
            "reviewUntil": at + timedelta(days=30), **audit})
        return {"retentionPolicyVerified": True, "reviewUntil": at + timedelta(days=30)}
    if command == "lookup":
        expected = email_hash(settings, email)
        return {"items": [public(row) for row in store.records()
            if hmac.compare_digest(row.get("ownerEmailHash", ""), expected)
            and (not row.get("expiresAt") or utc(row["expiresAt"]) > at)]}
    if command == "register":
        validate_keys(idempotency, receipt)
        with Session(db.engine) as session, session.begin():
            admins = db.table("MSP_ADMIN")
            account = session.execute(select(admins).where(admins.c.admin_id == admin_id)).mappings().first()
            active = store.active(admin_id)
            if active:
                verified_owner(settings, active, email)
                return public(active)
            if not account or not hmac.compare_digest(email_hash(settings, account.get("email") or ""), email_hash(settings, email)):
                raise Problem(403, "IDENTITY_NOT_VERIFIED")
            snapshot, _, members = capture(db, session, admin_id)
            pending_scope_allowed(store, snapshot)
            account = next(member for member in members if member["admin_id"] == admin_id)
            work = outstanding(db, session, snapshot)
            if snapshot["spots"]:
                rent = db.table("MSP_SPOT_RENT")
                current = session.execute(select(rent).where(rent.c.spot_master_id.in_([s["id"] for s in snapshot["spots"]])))
                if any(value.get("deletion_request_id") not in (None, request_id(idempotency)) for value in current.mappings()):
                    raise Problem(409, "DELETION_SCOPE_IN_PROGRESS")
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))
            actor = Principal(dict(account), "operator-verified", int(at.timestamp()))
            row = make_record(request, actor, snapshot, members, work, request_id(idempotency), receipt,
                body_digest({"channel": "EMAIL", "adminId": admin_id}))
            row.update(channel="EMAIL", verificationAudit=audit)
            row, _ = store.create(row)
            if row["ownerId"] != admin_id or row["receiptHash"] != digest(receipt):
                raise Problem(409, "IDEMPOTENCY_KEY_REUSED")
            if snapshot["scope"] == "SUBTREE":
                rent = db.table("MSP_SPOT_RENT")
                session.execute(update(rent).where(rent.c.spot_master_id.in_([s["id"] for s in snapshot["spots"]]))
                                .values(deletion_request_id=row["requestId"]))
        return public(row)
    row = store.get(ident)
    if not row:
        raise Problem(404, "DELETION_REQUEST_UNAVAILABLE")
    if command == "inspect":
        return {**public(row), "reviewRequired": row.get("reviewRequired", []),
                "steps": row.get("steps", {}), "attempts": row.get("attempts", 0), "overdue": row.get("overdue", False),
                "notificationResults": row.get("notificationResults", {}),
                "retentionReview": row.get("retentionReview", {})}
    if command == "rotate-receipt":
        verified_owner(settings, row, email)
        validate_keys("operator-receipt-key", receipt)
        store.update(ident, {"receiptHash": digest(receipt), "receiptRotationAudit": audit})
        return {"requestId": ident, "receiptRotated": True}
    if row["requestState"] in TERMINAL:
        raise Problem(409, "DELETION_STATE_INVALID")
    if command == "settlement":
        if row["scope"] != "SUBTREE" or row.get("steps", {}).get("withdrawal"):
            raise Problem(409, "DELETION_STATE_INVALID")
        with Session(db.engine) as session, session.begin():
            work = outstanding(db, session, row["snapshot"], external_confirmed=True)
            if any(work.values()):
                raise Problem(409, "OBLIGATIONS_NOT_SETTLED")
            eligible = row.get("eligibleAt") or at
            store.update(ident, {"externalSettlementConfirmedHash": row["scopeHash"], "externalSettlementAudit": audit,
                "eligibleAt": eligible, "processingDueAt": row.get("processingDueAt") or eligible + timedelta(days=7),
                "requestState": "PROCESSING", "nextAction": "NONE", "nextAttemptAt": None})
    elif command == "review":
        if not row.get("steps", {}).get("sql"):
            raise Problem(409, "DELETION_STATE_INVALID")
        report = report or {}
        if not set(row.get("reviewRequired", [])).issubset(set(report.get("reviewedCategories", []))):
            raise ValueError("The review must cover every reported category")
        retained = report.get("retainedData", [])
        for item in retained:
            if not all(item.get(field) for field in ("category", "fields", "purpose", "retentionBasis", "retentionUntil", "reason")):
                raise ValueError("Retained data requires fields, purpose, basis, deadline and reason")
        store.update(ident, {"dataReviewConfirmedHash": row["scopeHash"], "dataReviewAudit": audit,
            "retainedData": row.get("retainedData", []) + retained, "requestState": "PROCESSING", "nextAttemptAt": None})
    elif command == "resume":
        if row["requestState"] in ("WAITING_VERIFICATION", "WAITING_RECONFIRMATION"):
            raise Problem(409, "DELETION_RECONFIRMATION_REQUIRED")
        store.update(ident, {"requestState": "PROCESSING", "attempts": 0, "nextAttemptAt": None, "resumeAudit": audit})
    else:
        raise ValueError("Unknown operator action")
    return public(store.get(ident))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["policy", "lookup", "register", "rotate-receipt", "settlement", "review", "resume", "inspect"])
    parser.add_argument("--operator", required=True)
    parser.add_argument("--evidence-file", required=True)
    parser.add_argument("--request-id")
    parser.add_argument("--admin-id")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--verified-email-file")
    parser.add_argument("--receipt-file")
    parser.add_argument("--report-file")
    parser.add_argument("--log-days", type=int, default=30)
    parser.add_argument("--backup-days", type=int, default=30)
    args = parser.parse_args()
    if args.command in ("lookup", "register", "rotate-receipt") and not args.verified_email_file:
        parser.error("--verified-email-file is required after operator identity verification")
    if args.command in ("register", "rotate-receipt") and not args.receipt_file:
        parser.error("--receipt-file is required; never put the receipt in shell arguments")
    if args.command == "register" and (not args.admin_id or not args.idempotency_key):
        parser.error("register requires --admin-id and --idempotency-key")
    if args.command == "review" and not args.report_file:
        parser.error("review requires --report-file")
    if args.command not in ("policy", "lookup", "register") and not args.request_id:
        parser.error("--request-id is required")
    settings = Settings()
    db, store = Database(settings.database_url.get_secret_value()), DeletionStore(settings)
    try:
        result = act(db, settings, store, args.command, operator=args.operator,
            evidence=private_text(args.evidence_file), ident=args.request_id, admin_id=args.admin_id,
            idempotency=args.idempotency_key,
            email=private_text(args.verified_email_file) if args.verified_email_file else None,
            receipt=private_text(args.receipt_file) if args.receipt_file else None,
            report=json.loads(private_text(args.report_file)) if args.report_file else None,
            log_days=args.log_days, backup_days=args.backup_days)
        print(result)
    finally:
        if db.engine:
            db.engine.dispose()


if __name__ == "__main__":
    main()
