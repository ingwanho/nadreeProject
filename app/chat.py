"""Chat authentication and SQL-owned Firebase synchronization, using FCM credentials."""
import logging
import secrets
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import transaction
from app.errors import Problem
from app.firebase_auth import CustomerFirebaseAuth
from app.headers import bearer, refresh_header
from app.security import (PRIMARY, GENERAL, check_contract, fingerprint, lock_account,
                          now, principal, roles, user_principal)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Firebase chat"])
DB = Depends(transaction, scope="function")


def admin_uid(admin_id):
    return "nadree-admin-" + fingerprint(admin_id)


class ChatShop(BaseModel):
    shopId: str
    spotCode: str


class ChatSession(BaseModel):
    firebaseCustomToken: str
    firebaseUid: str
    managerId: str | None
    shops: list[ChatShop]
    region: str = "asia-northeast3"


class FirebaseChat:
    def __init__(self, settings):
        self.settings = settings
        self.identity = CustomerFirebaseAuth(settings)

    def store(self):
        if not self.settings.fcm_chat_enabled or not self.identity.configured:
            raise Problem(503, "CHAT_NOT_CONFIGURED")
        from firebase_admin import firestore
        from chat.functions.chat_core import ChatStore
        return ChatStore(firestore.client(app=self.identity._firebase_app()))

    def revoke(self, uid):
        if not self.settings.fcm_chat_enabled:
            return
        try:
            store = self.store()
            # Gate checked by both Rules and callable transactions; invalidate
            # before SQL commits. A SQL rollback can only remove access, not grant it.
            user = store.ref("chatUsers/" + uid)
            old = user.get().to_dict() or {}
            batch = store.db.batch()
            batch.set(user, {"active": False, "sessionId": secrets.token_urlsafe(32)}, merge=True)
            for shop in old.get("shopIds", []):
                batch.set(store.ref(f"chatShops/{shop}/members/{uid}"), {"active": False, "canReply": False})
            batch.delete(store.ref("chatPushTokens/" + uid))
            batch.commit()
        except Exception as error:
            raise Problem(503, "CHAT_SYNC_FAILED") from error

    def issue(self, uid, kind, subject, session_id, expires, shops, can_reply, fcm_token):
        try:
            from firebase_admin import auth
            store = self.store()
            app = self.identity._firebase_app()
            if kind == "admin":
                try:
                    account = auth.get_user(uid, app=app)
                except auth.UserNotFoundError:
                    account = auth.create_user(uid=uid, app=app)
                if account.disabled:
                    raise Problem(403, "CHAT_USER_DISABLED")
            else:
                account = auth.get_user(uid, app=app)
                if account.disabled:
                    raise Problem(403, "CHAT_USER_DISABLED")
            sid = secrets.token_urlsafe(32)
            user_ref = store.ref("chatUsers/" + uid)
            old = user_ref.get().to_dict() or {}
            batch = store.db.batch()
            current_shops = {s["shopId"] for s in shops}
            for shop in set(old.get("shopIds", [])) | current_shops:
                batch.set(store.ref(f"chatShops/{shop}/members/{uid}"),
                          {"active": shop in current_shops, "canReply": can_reply and shop in current_shops})
            batch.set(user_ref, {"active": True, "kind": kind, "subjectId": subject, "sessionId": sid,
                                "businessSessionId": session_id, "expiresAt": expires.replace(tzinfo=timezone.utc),
                                "shopIds": sorted(current_shops)})
            batch.set(store.ref("chatPushTokens/" + uid), {"token": fcm_token, "sessionId": sid})
            if fcm_token:
                batch.set(store.ref("chatPushTokenOwners/" + fingerprint(fcm_token)), {"uid": uid, "sessionId": sid})
            batch.commit()
            token = auth.create_custom_token(uid, {"chatSessionId": sid}, app=app)
            return {"firebaseCustomToken": token.decode() if isinstance(token, bytes) else token,
                    "firebaseUid": uid, "managerId": subject if kind == "admin" else None,
                    "shops": shops, "region": "asia-northeast3"}
        except Problem:
            raise
        except Exception as error:
            logger.error("Chat session sync failed: %s", type(error).__name__)
            raise Problem(503, "CHAT_SYNC_FAILED") from error

    def block_booking(self, ident):
        if self.settings.fcm_chat_enabled:
            try:
                self.store().block_booking(ident)
            except Exception as error:
                raise Problem(503, "CHAT_SYNC_FAILED") from error

    def sync_booking(self, db, ident):
        if not self.settings.fcm_chat_enabled:
            return
        table = db.table("MSP_RESERVATION")
        with Session(db.engine) as session, session.begin():
            row = session.execute(select(table).where(table.c.reservation_id == ident).with_for_update()).mappings().first()
            if row:
                self.store().sync_booking(ident, row["uid_token"], row["spot_master_id"], row["reservation_status"])


def revoke_admin_chat(request, admin_id):
    request.app.state.chat.revoke(admin_uid(admin_id))


def revoke_customer_chat(request, uid):
    request.app.state.chat.revoke(uid)


def queue_booking_chat(request, session, ident, status):
    if not request.app.state.settings.fcm_chat_enabled:
        return
    from chat.functions.chat_core import TERMINAL
    if status in TERMINAL:
        request.app.state.chat.block_booking(ident)
    session.info.setdefault("chat_bookings", set()).add(ident)


@router.post("/nadreego/chat/session", response_model=ChatSession, dependencies=[bearer],
             summary="관리자 Firebase 채팅 로그인",
             description="본문 없음. 현재 업무 세션과 직접 소속된 활성 지점만 검증하여 동기화 후 custom token 발급. 대표만 답변 가능. 401 업무 세션 만료, 403 역할/소속 거절, 503 CHAT_NOT_CONFIGURED 또는 CHAT_SYNC_FAILED. 상위 조직 권한은 채팅에 상속하지 않습니다.")
def admin_session(request: Request, session: Session = DB):
    actor = principal(request, session)
    account = lock_account(request, session, actor.admin["admin_id"], actor.session_id)
    db = request.app.state.db
    scope, master = db.table("MSP_ADMIN_SPOT_SCOPE"), db.table("MSP_SPOT_MASTER")
    rows = session.execute(select(master).join(scope, scope.c.spot_master_id == master.c.spot_master_id)
        .where(scope.c.admin_id == actor.admin["admin_id"], scope.c.access_type == "manage", master.c.is_active == 1)).mappings().all()
    shops = []
    for spot in rows:
        try:
            check_contract(session, db, spot, request.app.state.settings)
        except Problem:
            continue
        shops.append({"shopId": spot["spot_master_id"], "spotCode": spot["unit_code"]})
    if not shops:
        raise Problem(403, "CHAT_MEMBERSHIP_REQUIRED")
    if len(shops) > 200:
        raise Problem(503, "CHAT_MEMBERSHIP_LIMIT")
    tokens = db.table("MSP_REFRESH_TOKEN")
    expires = session.scalar(select(tokens.c.expires_at).where(tokens.c.token_id == actor.session_id))
    mapping = db.table("MSP_ADMIN_ROLE")
    role_expiry = session.scalars(select(mapping.c.expires_at).where(
        mapping.c.admin_id == actor.admin["admin_id"], mapping.c.role_code.in_([PRIMARY, GENERAL]),
        mapping.c.expires_at > now())).all()
    expires = min([expires, *role_expiry])
    contracts = db.table("MSP_CONTRACT")
    zone = ZoneInfo(request.app.state.settings.business_timezone)
    allowed_ids = {s["shopId"] for s in shops}
    for spot in rows:
        if spot["spot_master_id"] not in allowed_ids:
            continue
        end = session.scalar(select(contracts.c.end_date).where(contracts.c.contract_id == spot["contract_id"]))
        for last_day in (spot.get("contract_end"), end):
            if last_day and last_day < date.max:
                boundary = datetime.combine(last_day + timedelta(days=1), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
                expires = min(expires, boundary)
    request.app.state.limiter.check("chat-session:" + actor.admin["admin_id"], limit=10, seconds=60)
    return request.app.state.chat.issue(admin_uid(actor.admin["admin_id"]), "admin", actor.admin["admin_id"],
        actor.session_id, expires, shops, PRIMARY in roles(session, db, actor.admin["admin_id"]), account.get("fcm_token"))


@router.post("/api/v1/nadree/user/chat/session", response_model=ChatSession,
             dependencies=[bearer, Depends(refresh_header)], summary="고객 Firebase 채팅 세션 연결",
             description="현재 고객 access token과 X-Refresh-Token을 함께 검증합니다. 반환 custom token으로 Firebase 로그인 후 callable을 사용합니다. 이전 기기 토큰으로 새 채팅 세션을 발급할 수 없습니다.")
def customer_session(request: Request, session: Session = DB):
    from app.customer_rentals import _user_refresh_row
    from app.rental_common import lock_key
    user = user_principal(request, session)
    lock_key(session, "nadri-user", user.uid_token)
    table = request.app.state.db.table("MSP_RENTAL_USER")
    account = session.execute(select(table).where(table.c.uid_token == user.uid_token).with_for_update()).mappings().one()
    user_principal(request, session)
    _, token = _user_refresh_row(request, session, locked=True)
    if token["uid_token"] != user.uid_token:
        raise Problem(401, "TOKEN_PAIR_MISMATCH")
    return request.app.state.chat.issue(user.uid_token, "customer", user.uid_token, token["token_id"],
        token["expires_at"], [], False, account.get("fcm_token"))
