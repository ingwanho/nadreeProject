"""Recoverable Firestore-backed privacy work; SQL remains the authorization authority."""
import argparse
import logging
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.account_deletion_data import cleanup_chat, cleanup_sql
from app.account_deletion_scope import capture, gate, outstanding, pending_scope_allowed, scope_hash
from app.account_deletion_security import unseal
from app.account_deletion_store import TERMINAL, DeletionStore, utc
from app.chat import FirebaseChat, admin_uid
from app.config import Settings
from app.db import Database
from app.errors import Problem
from app.mail import PasswordMailer
from app.security import GENERAL, PRIMARY, SESSION_MARKER, now, roles

logger = logging.getLogger(__name__)


def save(store, row, **values):
    store.update(row["requestId"], values)
    row.update(values)


def contacts_for(settings, row):
    contacts = unseal(settings, row["privateContacts"])
    for contact in contacts:
        value = contact.get("phone")
        if value and value.startswith("gAAAA"):
            try:
                contact["phoneText"] = Fernet(settings.field_encrypt_key.get_secret_value().encode()).decrypt(value.encode()).decode()
            except (ValueError, TypeError, InvalidToken):
                contact["phoneReviewRequired"] = True
        elif value:
            contact["phoneText"] = value
    return contacts


def notify(store, row, mailer, contacts, *, completed=False):
    field = "completionNotified" if completed else "receivedNotified"
    sent = set(row.get(field, []))
    for contact in contacts:
        if contact["adminId"] in sent:
            continue
        if not contact.get("email"):
            raise Problem(503, "DELETION_NOTIFICATION_CONTACT_REQUIRED")
        mailer.send_deletion_notice(contact["email"], row["requestId"], completed=completed)
        sent.add(contact["adminId"])
        save(store, row, **{field: sorted(sent)})


def withdraw(db, store, chat, row, at):
    snapshot = row["snapshot"]
    master, rent, admins, mapping, tokens = (db.table(name) for name in (
        "MSP_SPOT_MASTER", "MSP_SPOT_RENT", "MSP_ADMIN", "MSP_ADMIN_ROLE", "MSP_REFRESH_TOKEN"))
    ids = [member["id"] for member in snapshot["admins"]]
    spot_ids = [spot["id"] for spot in snapshot["spots"]]
    with Session(db.engine) as session, session.begin():
        session.execute(select(master.c.spot_master_id).where(master.c.spot_master_id.in_(spot_ids))
                        .order_by(master.c.unit_code).with_for_update()).all()
        latest = store.get(row["requestId"])
        if latest["scopeHash"] != row["scopeHash"]:
            return False  # A concurrent reconfirmation has already saved a new scope.
        pending_scope_allowed(store, snapshot, request_id=row["requestId"])
        # A committed revocation may precede the Firestore checkpoint. Claims
        # and SQL gates prevent the old account from joining again in this gap.
        missing_roles = all(not roles(session, db, ident) & {PRIMARY, GENERAL} for ident in ids)
        if row.get("phase") == "WITHDRAWING" and missing_roles:
            pass
        else:
            current, _, _ = capture(db, session, row["ownerId"])
            if scope_hash(current) != row["scopeHash"]:
                save(store, row, requestState="WAITING_RECONFIRMATION", nextAction="RELOAD_AND_RECONFIRM")
                return False
            if snapshot["scope"] == "SUBTREE":
                for spot_id in spot_ids:
                    marker = gate(db, session, spot_id, lock=True)
                    if marker and marker != row["requestId"]:
                        raise Problem(409, "DELETION_SCOPE_IN_PROGRESS")
                session.execute(update(rent).where(rent.c.spot_master_id.in_(spot_ids))
                                .values(deletion_request_id=row["requestId"]))
            work = outstanding(db, session, snapshot,
                external_confirmed=row.get("externalSettlementConfirmedHash") == row["scopeHash"])
            if any(work.values()):
                save(store, row, requestState="WAITING_OBLIGATIONS", accessState="LIMITED_TO_SETTLEMENT",
                    outstandingWork=work, nextAction="SETTLE_OUTSTANDING_WORK")
                return False
            eligible = row.get("eligibleAt") or at
            save(store, row, phase="WITHDRAWING", requestState="PROCESSING", nextAction="NONE",
                eligibleAt=eligible, processingDueAt=row.get("processingDueAt") or eligible + timedelta(days=7),
                outstandingWork=work)
            session.execute(select(admins.c.admin_id).where(admins.c.admin_id.in_(ids))
                            .order_by(admins.c.admin_id).with_for_update()).all()
            if snapshot["scope"] == "SELF":
                from app.admin_rental_exit import transfer_approved_work
                transfer_approved_work(db, session, snapshot["rootId"], row["ownerId"])
        for ident in ids:
            chat.revoke(admin_uid(ident))
        session.execute(delete(mapping).where(mapping.c.admin_id.in_(ids), mapping.c.role_code.in_([PRIMARY, GENERAL])))
        session.execute(update(tokens).where(tokens.c.admin_id.in_(ids), tokens.c.user_agent == SESSION_MARKER,
            tokens.c.revoked_at.is_(None)).values(revoked_at=now()))
        session.execute(update(admins).where(admins.c.admin_id.in_(ids)).values(fcm_token=None, fcm_token_updated_at=now()))
        if snapshot["scope"] == "SUBTREE":
            session.execute(update(master).where(master.c.spot_master_id.in_(spot_ids)).values(is_active=0))
            for level in ("org", "region", "local", "spot"):
                codes = [spot["code"] for spot in snapshot["spots"] if spot["level"] == level]
                if codes:
                    normal = db.table("MSP_" + level.upper())
                    session.execute(update(normal).where(normal.c.contract_id == snapshot["contractId"],
                        normal.c.unit_code.in_(codes)).values(is_active=0))
    save(store, row, steps={**row.get("steps", {}), "withdrawal": True}, phase="ERASING",
         accessState="REVOKED", personalDataState="IN_PROGRESS", requestState="PROCESSING")
    return True


def process(db, settings, store, chat, mailer, row, at):
    if row["requestState"] in TERMINAL or row["requestState"] in ("WAITING_VERIFICATION", "WAITING_RECONFIRMATION"):
        return
    if row["requestState"] == "ACTION_REQUIRED" and row.get("nextAction") == "CONTACT_OPERATOR":
        return
    if row.get("nextAttemptAt") and utc(row["nextAttemptAt"]) > at:
        return
    contacts = contacts_for(settings, row)
    notify(store, row, mailer, contacts)
    if not row.get("steps", {}).get("withdrawal") and not withdraw(db, store, chat, row, at):
        return
    if not row.get("steps", {}).get("sql"):
        with Session(db.engine) as session, session.begin():
            retained, review = cleanup_sql(db, session, row["snapshot"], contacts)
        if any(contact.get("phoneReviewRequired") for contact in contacts):
            review.append("UNRESOLVED_PROFILE_PHONE")
        save(store, row, steps={**row.get("steps", {}), "sql": True}, retainedData=retained, reviewRequired=review)
    done = set(row.get("chatErased", []))
    for member in row["snapshot"]["admins"]:
        ident = member["id"]
        if ident in done:
            continue
        review = cleanup_chat(chat, ident, contacts)
        if review:
            save(store, row, reviewRequired=sorted(set(row.get("reviewRequired", [])) | {"OTHER_PARTY_CHAT_MENTIONS"}))
        deleted = chat.delete_admin_identity(ident)
        done.add(ident)
        values = {"chatErased": sorted(done)}
        if deleted:
            values["providerDeletionInitiatedAt"] = at
        save(store, row, **values)
    policy = store.get("policy_retention") or {}
    policy_valid = (policy.get("verified") is True and policy.get("activeStoresReviewed") is True
                    and policy.get("reviewUntil") and utc(policy["reviewUntil"]) >= at
                    and 0 <= policy.get("logMaxDays", -1) <= 30 and 0 <= policy.get("backupMaxDays", -1) <= 30)
    reviewed = row.get("dataReviewConfirmedHash") == row["scopeHash"]
    if not policy_valid or row.get("reviewRequired") and not reviewed:
        save(store, row, requestState="ACTION_REQUIRED", nextAction="REVIEW_DATA_AND_RETENTION",
            message="The request remains saved. An operator is reviewing shared content or retention controls.")
        return
    notify(store, row, mailer, contacts, completed=True)
    retained = row.get("retainedData", [])
    # Retain receipt/deduplication metadata only. Do not keep original identities,
    # contact ciphertext or affected account lists in a completed request.
    from app.account_deletions import PUBLIC_FIELDS
    final = {name: row[name] for name in PUBLIC_FIELDS if name in row}
    final.update(recordType="request", receiptHash=row["receiptHash"], bodyDigest=row["bodyDigest"],
        ownerEmailHash=row["ownerEmailHash"], requestState="COMPLETED_WITH_RETENTION" if retained else "COMPLETED",
        personalDataState="COMPLETED", completedAt=at, nextAction="NONE", completionScope="COMPANY_ACTIVE_SYSTEMS",
        receiptExpiresAt=at + timedelta(days=30), expiresAt=at + timedelta(days=30), updatedAt=at,
        message="Deletion in company active systems is complete. Retained information and residual copies follow the stated policies.",
        residualCopies=[{"category": "COMPANY_RESTRICTED_BACKUP", "deleteBy": at + timedelta(days=policy["backupMaxDays"])},
            {"category": "COMPANY_LOG_RETENTION", "deleteBy": at + timedelta(days=policy["logMaxDays"])}])
    if row.get("providerDeletionInitiatedAt"):
        final["residualCopies"].append({"category": "FIREBASE_AUTH_PROVIDER_RESIDUAL",
            "providerDeletionInitiatedAt": row["providerDeletionInitiatedAt"],
            "providerNoticeUrl": "https://firebase.google.com/support/privacy"})
    final["reviewEvidenceHash"] = row.get("dataReviewAudit", {}).get("evidenceHash")
    final["policyEvidenceHash"] = policy.get("evidenceHash")
    if row.get("reconfirmationDigest"):
        final["reconfirmationDigest"] = row["reconfirmationDigest"]
    store.finish(row, final)


def run(db, settings, store, chat, mailer, *, at=None):
    at = utc(at)
    counts = {"processed": 0, "deferred": 0, "completed": 0, "expiredReceipts": 0}
    with db.engine.connect() as connection:
        mysql = connection.dialect.name == "mysql"
        name = "nadree:job:account-deletions"
        if mysql and connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": name}) != 1:
            return {"busy": True}
        try:
            for row in store.pending():
                counts["processed"] += 1
                try:
                    process(db, settings, store, chat, mailer, row, at)
                    latest = store.get(row["requestId"])
                    counts["completed"] += latest["requestState"] in TERMINAL
                    if latest.get("processingDueAt") and utc(latest["processingDueAt"]) < at and latest["requestState"] not in TERMINAL:
                        store.update(row["requestId"], {"requestState": "ACTION_REQUIRED", "nextAction": "CONTACT_OPERATOR", "overdue": True})
                        logger.error("Deletion request overdue: %s", row["requestId"])
                except Exception as error:
                    attempts = row.get("attempts", 0) + 1
                    overdue = bool(row.get("processingDueAt") and utc(row["processingDueAt"]) < at)
                    needs_operator = attempts >= 5 or overdue
                    store.update(row["requestId"], {"requestState": "ACTION_REQUIRED" if needs_operator else "RETRYING",
                        "attempts": attempts, "nextAttemptAt": at + timedelta(minutes=min(60, 2 ** min(attempts, 6))),
                        "nextAction": "CONTACT_OPERATOR" if needs_operator else "NONE", "overdue": overdue,
                        "message": "The saved request is awaiting a retry or operator action."})
                    counts["deferred"] += 1
                    logger.warning("Deletion request deferred: %s %s", row["requestId"], type(error).__name__)
                    if needs_operator:
                        logger.error("Deletion operator action required: %s", row["requestId"])
            counts["expiredReceipts"] = store.remove_expired(at)
        finally:
            if mysql:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    db, store = Database(settings.database_url.get_secret_value()), DeletionStore(settings)
    try:
        if not args.apply:
            print({"pendingRequests": sum(1 for _ in store.pending()), "mode": "plan"})
            return
        result = run(db, settings, store, FirebaseChat(settings), PasswordMailer(settings))
        print(result)
        if result.get("deferred"):
            raise SystemExit(1)
    finally:
        if db.engine:
            db.engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    main()
