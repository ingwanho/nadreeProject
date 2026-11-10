"""Authenticated acceptance and receipt-only progress for administrator privacy requests."""
import logging
from datetime import timedelta

from fastapi import APIRouter, Header, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import Field, SecretStr, StrictBool
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.account_deletion_scope import capture, gate, outstanding, pending_scope_allowed, request_execution, scope_hash
from app.account_deletion_security import confirmation, email_hash, seal, validate_keys, verify_confirmation
from app.account_deletion_store import body_digest, digest, receipt_matches, request_id, utc
from app.spot_hierarchy import unit_name
from app.errors import Problem
from app.headers import bearer
from app.responses import AccountDeletionContext, AccountDeletionRequestResult
from app.schemas import Body
from app.security import principal

router = APIRouter(prefix="/nadreego/admin", tags=["W01 Accounts"])
receipt_auth = APIKeyHeader(name="Authorization", scheme_name="DeletionReceipt", auto_error=False,
                           description="DeletionReceipt <receipt secret saved before submission>")
logger = logging.getLogger(__name__)
PUBLIC_FIELDS = {"requestId", "requestState", "scope", "receivedAt", "identityVerifiedAt", "eligibleAt",
    "processingDueAt", "completedAt", "accessState", "personalDataState", "outstandingWork",
    "affectedAdminCount", "affectedShopCount", "nextAction", "notificationChannel", "completionScope",
    "retainedData", "residualCopies", "receiptExpiresAt", "message"}


class DeletionConfirmation(Body):
    confirmationToken: SecretStr = Field(min_length=1, max_length=8192)
    confirmed: StrictBool


def public(row):
    return {"status": "success", "requestAccepted": True,
            **{name: row[name] for name in PUBLIC_FIELDS if name in row}}


def replay(row, secret, fingerprint):
    if not receipt_matches(row, secret):
        return None
    if row.get("expiresAt") and utc(row["expiresAt"]) <= utc():
        raise Problem(404, "DELETION_REQUEST_UNAVAILABLE")
    if row.get("bodyDigest") != fingerprint:
        raise Problem(409, "IDEMPOTENCY_KEY_REUSED", request_outcome={"requestAccepted": False})
    return public(row)


def storage(operation, *, saving=False):
    try:
        return operation()
    except Problem:
        raise
    except Exception as error:
        logger.warning("Deletion storage deferred: %s", type(error).__name__)
        raise Problem(503, "DELETION_OUTCOME_UNKNOWN" if saving else "DELETION_STATUS_UNAVAILABLE") from None


def require_schema(db):
    if "deletion_request_id" not in db.table("MSP_SPOT_RENT").c:
        raise Problem(503, "DELETION_SCHEMA_UPDATE_REQUIRED", request_outcome={"requestAccepted": False})


def limited(request, subject):
    ip = request.client.host if request.client else "unknown"
    request.app.state.limiter.check("account-deletion:ip:" + ip, limit=30)
    request.app.state.limiter.check("account-deletion:subject:" + subject, limit=30)


def context_data(request, session, actor):
    snapshot, root, members = capture(request.app.state.db, session, actor.admin["admin_id"])
    store = request.app.state.deletions
    active = storage(lambda: store.active(actor.admin["admin_id"]))
    confirmed = bool(active and active.get("externalSettlementConfirmedHash") == scope_hash(snapshot))
    work = outstanding(request.app.state.db, session, snapshot, external_confirmed=confirmed)
    token, expires = confirmation(request.app.state.settings, actor.admin["admin_id"], scope_hash(snapshot))
    return {"status": "success", "scope": snapshot["scope"], "directShopName": unit_name(root),
        "affectedAdminCount": len(members), "affectedShopCount": len(snapshot["spots"]) if snapshot["scope"] == "SUBTREE" else 0,
        "confirmationToken": token, "confirmationExpiresAt": expires, "outstandingWork": work,
        "canSubmitRequest": True, "canExecuteWithdrawal": not any(work.values()),
        "activeRequestId": active["requestId"] if active else None}, snapshot, members


@router.get("/account-deletion-context", response_model=AccountDeletionContext, dependencies=[bearer],
            summary="Review the administrator personal-data deletion scope",
            description="Checks the current role, shop affiliation, full descendant hierarchy, and unfinished work, then issues a confirmation token valid for 10 minutes. Deletion targets cannot be selected through request input.")
def deletion_context(request: Request):
    store, db = request.app.state.deletions, request.app.state.db
    if not store.configured:
        raise Problem(503, "DELETION_NOT_CONFIGURED")
    require_schema(db)
    with Session(db.engine) as session, session.begin():
        actor = principal(request, session)
        limited(request, actor.admin["admin_id"])
        return context_data(request, session, actor)[0]


def make_record(request, actor, snapshot, members, work, ident, secret, fingerprint):
    at = utc()
    ready = not any(work.values())
    addresses = [{"adminId": member["admin_id"], "email": member.get("email"),
                  "name": member.get("admin_name"), "phone": member.get("phone")} for member in members]
    return {"recordType": "request", "requestId": ident, "ownerId": actor.admin["admin_id"],
        "receiptHash": digest(secret), "bodyDigest": fingerprint,
        "ownerEmailHash": email_hash(request.app.state.settings, actor.admin.get("email") or ""),
        "snapshot": snapshot, "scopeHash": scope_hash(snapshot), "privateContacts": seal(request.app.state.settings, addresses),
        "scope": snapshot["scope"], "affectedAdminCount": len(members),
        "affectedShopCount": len(snapshot["spots"]) if snapshot["scope"] == "SUBTREE" else 0,
        "receivedAt": at, "identityVerifiedAt": at, "eligibleAt": at if ready else None,
        "processingDueAt": at + timedelta(days=7) if ready else None, "completedAt": None,
        "requestState": "PROCESSING" if ready else "WAITING_OBLIGATIONS",
        "accessState": "PENDING" if ready else "LIMITED_TO_SETTLEMENT",
        "personalDataState": "NOT_STARTED", "outstandingWork": work,
        "nextAction": "NONE" if ready else "SETTLE_OUTSTANDING_WORK", "notificationChannel": "REGISTERED_EMAIL",
        "message": "Your account and personal-data deletion request has been received.",
        "steps": {}, "attempts": 0, "updatedAt": at, "channel": "APP"}


@router.post("/account-deletion-requests", response_model=AccountDeletionRequestResult, status_code=202, dependencies=[bearer],
             summary="Submit administrator withdrawal and personal-data deletion",
             description="Accepts the request using the current authentication and confirmation token. On first acceptance, a general administrator's approved unfinished work is transferred to the primary administrator of the same shop, and roles, sessions, and chat access are revoked and FCM tokens are cleared before accessState=REVOKED is returned. The background job continues personal-data cleanup without another submission. Primary administrators retain the existing background workflow and wait in WAITING_OBLIGATIONS while unfinished work remains in their shop or any descendant shop. Business records are neither canceled nor deleted. State is stored in FCM Firestore. Save Idempotency-Key and a random Deletion-Receipt-Token of at least 256 bits before submission. Repeating the same key, receipt, and body only reads the existing result. Acceptance does not mean personal-data deletion is complete.")
def submit_deletion(body: DeletionConfirmation, request: Request,
                    idempotency_key: str = Header(alias="Idempotency-Key", max_length=64),
                    receipt_token: SecretStr = Header(alias="Deletion-Receipt-Token", max_length=128)):
    secret = receipt_token.get_secret_value()
    validate_keys(idempotency_key, secret)
    limited(request, request_id(idempotency_key))
    if not body.confirmed:
        raise Problem(422, "INVALID_CONFIRMATION", request_outcome={"requestAccepted": False})
    store, db, ident = request.app.state.deletions, request.app.state.db, request_id(idempotency_key)
    require_schema(db)
    fingerprint = body_digest({"confirmationToken": body.confirmationToken.get_secret_value(), "confirmed": True})
    existing = storage(lambda: store.get(ident))
    repeated = replay(existing, secret, fingerprint)
    if repeated is not None:
        return repeated
    with request_execution(db, ident, wait_seconds=10) as acquired:
        if not acquired:
            raise Problem(503, "DELETION_REQUEST_BUSY", request_outcome={"requestAccepted": False})
        # A competing first call may have revoked the session while we waited.
        # Authenticate a new acceptance only after checking its exact replay.
        existing = storage(lambda: store.get(ident))
        repeated = replay(existing, secret, fingerprint)
        if repeated is not None:
            return repeated
        with Session(db.engine) as session, session.begin():
            actor = principal(request, session)
            _, snapshot, members = context_data(request, session, actor)
            verify_confirmation(request.app.state.settings, body.confirmationToken.get_secret_value(),
                                actor.admin["admin_id"], scope_hash(snapshot))
            if existing:
                raise Problem(409, "IDEMPOTENCY_KEY_REUSED", request_outcome={"requestAccepted": False})
            active = storage(lambda: store.active(actor.admin["admin_id"]))
            if active:
                raise Problem(409, "DELETION_REQUEST_ALREADY_ACTIVE", request_outcome={"requestAccepted": False})
            pending_scope_allowed(store, snapshot)
            work = outstanding(db, session, snapshot)
            for spot in snapshot["spots"]:
                current = gate(db, session, spot["id"], lock=True)
                if current and current != ident:
                    raise Problem(409, "DELETION_SCOPE_IN_PROGRESS", request_outcome={"requestAccepted": False})
            row = make_record(request, actor, snapshot, members, work, ident, secret, fingerprint)
            # Keep recoverable consent before SQL revocation or external work.
            row, created = storage(lambda: store.create(row), saving=True)
            request.state.deletion_saved = True
            if not receipt_matches(row, secret) or row.get("bodyDigest") != fingerprint:
                raise Problem(409, "IDEMPOTENCY_KEY_REUSED", request_outcome={"requestAccepted": False})
            if snapshot["scope"] == "SUBTREE":
                rent = db.table("MSP_SPOT_RENT")
                session.execute(update(rent).where(rent.c.spot_master_id.in_([s["id"] for s in snapshot["spots"]]))
                                .values(deletion_request_id=ident))
        if created and row["scope"] == "SELF":
            from app.account_deletion_jobs import withdraw
            try:
                # Acceptance's transaction has released its locks. The worker
                # cannot touch this receipt until this first withdrawal exits.
                withdraw(db, store, request.app.state.chat, row, utc())
            except Exception as error:
                logger.warning("Immediate deletion withdrawal deferred: %s %s", ident, type(error).__name__)
                raise Problem(503, "DELETION_OUTCOME_UNKNOWN") from None
        latest = storage(lambda: store.get(ident), saving=True)
        if not latest:
            raise Problem(503, "DELETION_OUTCOME_UNKNOWN")
        return public(latest)


@router.get("/account-deletion-requests/status", response_model=AccountDeletionRequestResult,
            summary="Get deletion-request progress after withdrawal",
            description="Use Authorization: DeletionReceipt <secret saved before submission> and the original Idempotency-Key. This receipt grants access only to its request, not to regular APIs. Deletion targets and secrets are not included in responses or URLs. A 404 response does not disclose whether a request exists or a receipt is valid.")
def deletion_status(request: Request, authorization: str | None = Security(receipt_auth),
                    idempotency_key: str = Header(alias="Idempotency-Key", max_length=64)):
    raw = authorization or ""
    secret = raw[len("DeletionReceipt "):] if raw.startswith("DeletionReceipt ") else ""
    validate_keys(idempotency_key, secret)
    limited(request, request_id(idempotency_key))
    row = storage(lambda: request.app.state.deletions.get(request_id(idempotency_key)))
    if not receipt_matches(row, secret):
        raise Problem(404, "DELETION_REQUEST_UNAVAILABLE")
    if row.get("expiresAt") and utc(row["expiresAt"]) <= utc():
        raise Problem(404, "DELETION_REQUEST_UNAVAILABLE")
    return public(row)


@router.post("/account-deletion-requests/{deletion_id}/reconfirm", response_model=AccountDeletionRequestResult,
             status_code=202, dependencies=[bearer], summary="Reconfirm a changed deletion scope")
def reconfirm_deletion(deletion_id: str, body: DeletionConfirmation, request: Request,
                       receipt_token: SecretStr = Header(alias="Deletion-Receipt-Token", max_length=128)):
    store, db = request.app.state.deletions, request.app.state.db
    if not body.confirmed:
        raise Problem(422, "INVALID_CONFIRMATION")
    fingerprint = body_digest({"confirmationToken": body.confirmationToken.get_secret_value(), "confirmed": True})
    row = storage(lambda: store.get(deletion_id))
    if row and row.get("expiresAt") and utc(row["expiresAt"]) <= utc():
        raise Problem(404, "DELETION_REQUEST_UNAVAILABLE")
    if receipt_matches(row, receipt_token.get_secret_value()) and row.get("reconfirmationDigest") == fingerprint:
        limited(request, deletion_id)
        return public(row)
    with Session(db.engine) as session, session.begin():
        actor = principal(request, session)
        limited(request, actor.admin["admin_id"])
        row = storage(lambda: store.get(deletion_id))
        if not receipt_matches(row, receipt_token.get_secret_value()) or row.get("ownerId") != actor.admin["admin_id"]:
            raise Problem(404, "DELETION_REQUEST_UNAVAILABLE")
        if row["requestState"] != "WAITING_RECONFIRMATION":
            raise Problem(409, "DELETION_STATE_INVALID")
        snapshot, _, members = capture(db, session, actor.admin["admin_id"])
        verify_confirmation(request.app.state.settings, body.confirmationToken.get_secret_value(),
                            actor.admin["admin_id"], scope_hash(snapshot))
        pending_scope_allowed(store, snapshot, request_id=deletion_id)
        for spot in snapshot["spots"]:
            value = gate(db, session, spot["id"], lock=True)
            if value and value != deletion_id:
                raise Problem(409, "DELETION_SCOPE_IN_PROGRESS")
        work = outstanding(db, session, snapshot)
        contacts = [{"adminId": m["admin_id"], "email": m.get("email"), "name": m.get("admin_name"), "phone": m.get("phone")} for m in members]
        changes = {"snapshot": snapshot, "scopeHash": scope_hash(snapshot), "scope": snapshot["scope"],
            "affectedAdminCount": len(members), "affectedShopCount": len(snapshot["spots"]) if snapshot["scope"] == "SUBTREE" else 0,
            "privateContacts": seal(request.app.state.settings, contacts), "reconfirmationDigest": fingerprint,
            "requestState": "WAITING_OBLIGATIONS" if any(work.values()) else "PROCESSING",
            "outstandingWork": work, "nextAction": "SETTLE_OUTSTANDING_WORK" if any(work.values()) else "NONE"}
        storage(lambda: store.update(deletion_id, changes), saving=True)
        request.state.deletion_saved = True
        rent = db.table("MSP_SPOT_RENT")
        session.execute(update(rent).where(rent.c.deletion_request_id == deletion_id).values(deletion_request_id=None))
        if snapshot["scope"] == "SUBTREE":
            session.execute(update(rent).where(rent.c.spot_master_id.in_([s["id"] for s in snapshot["spots"]]))
                            .values(deletion_request_id=deletion_id))
    return public({**row, **changes})
