"""Authenticated acceptance and receipt-only progress for administrator privacy requests."""
import logging
from datetime import timedelta

from fastapi import APIRouter, Header, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import Field, SecretStr, StrictBool
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.account_deletion_scope import capture, gate, outstanding, pending_scope_allowed, scope_hash
from app.account_deletion_security import confirmation, email_hash, seal, validate_keys, verify_confirmation
from app.account_deletion_store import body_digest, digest, receipt_matches, request_id, utc
from app.errors import Problem
from app.headers import bearer
from app.responses import AccountDeletionContext, AccountDeletionRequestResult
from app.schemas import Body
from app.security import principal

router = APIRouter(prefix="/nadreego/admin", tags=["W01 Accounts"])
receipt_auth = APIKeyHeader(name="Authorization", scheme_name="DeletionReceipt", auto_error=False,
                           description="DeletionReceipt <전송 전 보관한 조회 비밀값>")
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
    return {"status": "success", "scope": snapshot["scope"], "directShopName": root["spot_name"],
        "affectedAdminCount": len(members), "affectedShopCount": len(snapshot["spots"]) if snapshot["scope"] == "SUBTREE" else 0,
        "confirmationToken": token, "confirmationExpiresAt": expires, "outstandingWork": work,
        "canSubmitRequest": True, "canExecuteWithdrawal": not any(work.values()),
        "activeRequestId": active["requestId"] if active else None}, snapshot, members


@router.get("/account-deletion-context", response_model=AccountDeletionContext, dependencies=[bearer],
            summary="관리자 개인정보 삭제 범위 확인",
            description="현재 역할·소속·전체 하위 계층과 미완료 업무를 확인하고 10분 유효 확인 토큰을 발급합니다. 입력으로 삭제 대상을 선택하지 않습니다.")
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
             summary="관리자 탈퇴·개인정보 삭제 요청 접수",
             description="현재 인증과 확인 토큰으로 접수합니다. 대표는 모든 하위 지점의 미완료 업무가 있으면 WAITING_OBLIGATIONS로 대기하며 실제 삭제하지 않습니다. 일반은 본인이 승인한 미완료 업무를 같은 지점 대표에게 인계하며 업무 데이터는 취소/삭제하지 않습니다. FCM Firestore에 상태를 저장합니다. Idempotency-Key와 256비트 이상 무작위 Deletion-Receipt-Token을 전송 전에 보관합니다. 접수는 개인정보 삭제 완료가 아닙니다.")
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
    if existing and receipt_matches(existing, secret):
        if existing.get("expiresAt") and utc(existing["expiresAt"]) <= utc():
            raise Problem(404, "DELETION_REQUEST_UNAVAILABLE")
        if existing.get("bodyDigest") != fingerprint:
            raise Problem(409, "IDEMPOTENCY_KEY_REUSED", request_outcome={"requestAccepted": False})
        return public(existing)
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
        # Durable acceptance precedes SQL side effects. If SQL subsequently fails,
        # the same Firestore request is recovered by the worker, not forgotten.
        row, _ = storage(lambda: store.create(row), saving=True)
        request.state.deletion_saved = True
        if not receipt_matches(row, secret) or row.get("bodyDigest") != fingerprint:
            raise Problem(409, "IDEMPOTENCY_KEY_REUSED", request_outcome={"requestAccepted": False})
        if snapshot["scope"] == "SUBTREE":
            rent = db.table("MSP_SPOT_RENT")
            session.execute(update(rent).where(rent.c.spot_master_id.in_([s["id"] for s in snapshot["spots"]]))
                            .values(deletion_request_id=ident))
    # Do not couple acceptance to all external erasure/SMTP work. The worker
    # returns the same receipt state after reboot or provider failure.
    return public(row)


@router.get("/account-deletion-requests/status", response_model=AccountDeletionRequestResult,
            summary="탈퇴 후 삭제 요청 진행 조회",
            description="Authorization: DeletionReceipt <전송 전 보관한 비밀값>와 원래 Idempotency-Key로 조회합니다. 일반 API 접근 권한이 없는 요청 한정 영수증이며 삭제 대상/비밀값은 응답·URL에 넣지 않습니다. 404는 존재/영수증 유효성을 공개하지 않습니다.")
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
             status_code=202, dependencies=[bearer], summary="변경된 삭제 범위 재확인")
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
