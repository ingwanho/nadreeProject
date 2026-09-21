"""Best-effort FCM delivery for committed rental events.

FCM tokens remain in the shared rental tables.  Notifications are queued in the
request transaction and dispatched only after that transaction commits, so a
failed push cannot make a reservation or payment appear successful when its
database write was rolled back.
"""

import logging
import random
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from sqlalchemy import and_, select, update

from app.security import GENERAL, PRIMARY

logger = logging.getLogger(__name__)


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FcmSender:
    def __init__(self, settings):
        self.settings = settings
        self._app = None
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="nadree-fcm")

    @property
    def configured(self):
        settings = self.settings
        return bool(settings.fcm_project_id and settings.fcm_client_email and
                    settings.fcm_private_key.get_secret_value())

    def _firebase_app(self):
        if not self.configured:
            raise RuntimeError("FCM_NOT_CONFIGURED")
        with self._lock:
            if self._app is not None:
                return self._app
            try:
                import firebase_admin
                from firebase_admin import credentials
            except ImportError as exc:
                raise RuntimeError("FCM_SDK_NOT_INSTALLED") from exc
            info = {
                "type": self.settings.fcm_credential_type,
                "project_id": self.settings.fcm_project_id,
                "private_key_id": self.settings.fcm_private_key_id,
                "private_key": self.settings.fcm_private_key.get_secret_value().replace("\\n", "\n"),
                "client_email": self.settings.fcm_client_email,
                "client_id": self.settings.fcm_client_id,
                "auth_uri": self.settings.fcm_auth_uri,
                "token_uri": self.settings.fcm_token_uri,
                "auth_provider_x509_cert_url": self.settings.fcm_auth_provider_x509_cert_url,
                "client_x509_cert_url": self.settings.fcm_client_x509_cert_url,
                "universe_domain": self.settings.fcm_universe_domain,
            }
            try:
                self._app = firebase_admin.get_app("nadree-fcm")
            except ValueError:
                self._app = firebase_admin.initialize_app(
                    credentials.Certificate(info), {"projectId": self.settings.fcm_project_id},
                    name="nadree-fcm")
            return self._app

    def dispatch(self, db, notifications):
        """Send queued messages without raising into the business request."""
        if not notifications:
            return
        if not self.configured:
            logger.warning("FCM is not configured; skipped %d notification(s)", len(notifications))
            return
        for notification in notifications:
            self._executor.submit(self._deliver_with_retry, db, notification)

    def _deliver_with_retry(self, db, notification):
        pending = notification
        deadline = time.monotonic() + 3600
        for attempt in range(5):
            pending = self._current_recipients(db, pending)
            if not pending["recipients"]:
                return
            try:
                invalid, retryable, retry_after = self._send(pending)
                if invalid:
                    self._clear_invalid_tokens(db, pending, invalid)
                if not retryable:
                    return
                pending = dict(pending, recipients=retryable)
            except Exception as exc:
                # Provider/network errors apply to the still-current recipients.
                retry_after = getattr(exc, "retry_after", None)
                logger.warning("FCM attempt %d failed for event %s: %s", attempt + 1,
                               notification.get("event"), type(exc).__name__)
            if attempt == 4:
                break
            delay = self._retry_delay(attempt, retry_after)
            if time.monotonic() + delay > deadline:
                break
            time.sleep(delay + random.uniform(0, min(1.0, delay * 0.1)))
        logger.error("FCM delivery exhausted for event %s", notification.get("event"))

    @staticmethod
    def _retry_delay(attempt, retry_after):
        if isinstance(retry_after, (int, float)) and retry_after >= 0:
            return min(float(retry_after), 3600)
        return min(2 ** attempt, 60)

    def _send(self, notification):
        from firebase_admin import messaging

        recipients = notification.get("recipients", [])
        invalid, retryable = [], []
        retry_after = None
        app = self._firebase_app()
        for offset in range(0, len(recipients), 500):
            batch = recipients[offset:offset + 500]
            message = messaging.MulticastMessage(
                notification=messaging.Notification(notification["title"], notification["body"]),
                data={key: str(value) for key, value in notification.get("data", {}).items()
                      if value is not None},
                tokens=[item["token"] for item in batch],
            )
            response = messaging.send_each_for_multicast(message, app=app)
            for item, result in zip(batch, response.responses):
                error = result.exception
                if error is None:
                    continue
                code = getattr(error, "code", "")
                if isinstance(error, messaging.UnregisteredError) or code in {
                    "unregistered", "registration-token-not-registered"
                }:
                    invalid.append(item)
                elif code in {"quota-exceeded", "unavailable", "internal"}:
                    retryable.append(item)
                    if code == "quota-exceeded":
                        retry_after = 60
                else:
                    logger.warning("FCM provider rejected event %s for one recipient: %s",
                                   notification.get("event"), code or type(error).__name__)
        return invalid, retryable, retry_after

    @staticmethod
    def _current_recipients(db, notification):
        table = db.table(notification["table"])
        key = table.c[notification["key_column"]]
        columns = [key, table.c.fcm_token, table.c.fcm_token_updated_at]
        active = table.c.is_active if "is_active" in table.c else None
        if active is not None:
            columns.append(active)
        current = []
        with db.engine.connect() as connection:
            for item in notification.get("recipients", []):
                row = connection.execute(select(*columns).where(key == item["id"])).mappings().first()
                if not row or not row["fcm_token"] or row["fcm_token"] != item["token"]:
                    continue
                if active is not None and row["is_active"] != 1:
                    continue
                if row["fcm_token_updated_at"] != item.get("updated_at"):
                    continue
                current.append(item)
        return dict(notification, recipients=current)

    @staticmethod
    def _clear_invalid_tokens(db, notification, invalid):
        table = db.table(notification["table"])
        key = table.c[notification["key_column"]]
        with db.engine.begin() as connection:
            for item in invalid:
                updated_at = table.c.fcm_token_updated_at
                updated_condition = (updated_at.is_(None) if item.get("updated_at") is None
                                     else updated_at == item["updated_at"])
                connection.execute(update(table).where(
                    and_(key == item["id"], table.c.fcm_token == item["token"], updated_condition)).values(
                        fcm_token=None, fcm_token_updated_at=_utc_now()))

    def close(self):
        # firebase-admin owns its process-wide app.  It is intentionally kept
        # alive when a TestClient or an application lifespan is closed.
        self._app = None
        self._executor.shutdown(wait=False, cancel_futures=True)


def _queue(session, *, table, key_column, recipients, event, title, body, data):
    recipients = [item for item in recipients if item.get("token")]
    if not recipients:
        return
    session.info.setdefault("fcm_notifications", []).append({
        "table": table,
        "key_column": key_column,
        "recipients": recipients,
        "event": event,
        "title": title,
        "body": body,
        "data": data,
    })


def _manager_recipients(db, session, spot_master_id):
    admins, mapping, roles, scopes = (db.table(name) for name in (
        "MSP_ADMIN", "MSP_ADMIN_ROLE", "MSP_ROLE", "MSP_ADMIN_SPOT_SCOPE"))
    query = (select(admins.c.admin_id, admins.c.fcm_token, admins.c.fcm_token_updated_at)
             .select_from(admins.join(mapping, mapping.c.admin_id == admins.c.admin_id)
                          .join(roles, roles.c.role_code == mapping.c.role_code)
                          .join(scopes, and_(scopes.c.admin_id == admins.c.admin_id,
                                             scopes.c.spot_master_id == spot_master_id)))
             .where(admins.c.primary_spot_master_id == spot_master_id,
                    admins.c.is_active == 1, admins.c.fcm_token.is_not(None),
                    mapping.c.role_code.in_([PRIMARY, GENERAL]), roles.c.is_active == 1,
                    scopes.c.access_type == "manage",
                    (mapping.c.expires_at.is_(None) | (mapping.c.expires_at > _utc_now())))
             .distinct())
    return [{"id": row.admin_id, "token": row.fcm_token, "updated_at": row.fcm_token_updated_at}
            for row in session.execute(query)]


def queue_reservation_request(db, session, reservation_id, spot_master_id):
    _queue(session, table="MSP_ADMIN", key_column="admin_id",
           recipients=_manager_recipients(db, session, spot_master_id),
           event="RESERVATION_REQUESTED", title="새 예약 요청",
           body="새 렌트 예약 요청이 도착했습니다.",
           data={"type": "RESERVATION_REQUESTED", "reservationId": reservation_id,
                 "bookedNo": "BO" + reservation_id, "reservationStatus": "REQUESTED"})


def queue_reservation_decision(db, session, uid_token, reservation_id, status):
    users = db.table("MSP_RENTAL_USER")
    row = session.execute(select(users.c.uid_token, users.c.fcm_token, users.c.fcm_token_updated_at).where(
        users.c.uid_token == uid_token)).mappings().first()
    if not row:
        return
    approved = status == "APPROVED"
    _queue(session, table="MSP_RENTAL_USER", key_column="uid_token",
           recipients=[{"id": row["uid_token"], "token": row.get("fcm_token"),
                        "updated_at": row.get("fcm_token_updated_at")}],
           event="RESERVATION_APPROVED" if approved else "RESERVATION_REJECTED",
           title="예약 승인 완료" if approved else "예약 거절 안내",
           body="렌트 예약이 승인되었습니다. 결제를 진행해 주세요." if approved
           else "요청하신 렌트 예약이 거절되었습니다.",
           data={"type": "RESERVATION_APPROVED" if approved else "RESERVATION_REJECTED",
                 "reservationId": reservation_id, "bookedNo": "BO" + reservation_id,
                 "reservationStatus": status})


def queue_payment_complete(db, session, uid_token, reservation_id, spot_master_id, payment_id):
    _queue(session, table="MSP_ADMIN", key_column="admin_id",
           recipients=_manager_recipients(db, session, spot_master_id),
           event="PAYMENT_COMPLETED", title="결제 완료",
           body="관광객의 렌트 결제가 완료되었습니다.",
           data={"type": "PAYMENT_COMPLETED", "reservationId": reservation_id,
                 "paymentId": payment_id, "paymentStatus": "PAID"})
    users = db.table("MSP_RENTAL_USER")
    row = session.execute(select(users.c.uid_token, users.c.fcm_token, users.c.fcm_token_updated_at).where(
        users.c.uid_token == uid_token)).mappings().first()
    if row:
        _queue(session, table="MSP_RENTAL_USER", key_column="uid_token",
               recipients=[{"id": row["uid_token"], "token": row.get("fcm_token"),
                            "updated_at": row.get("fcm_token_updated_at")}],
               event="PAYMENT_COMPLETED", title="결제 완료",
               body="렌트 결제가 완료되었습니다.",
               data={"type": "PAYMENT_COMPLETED", "reservationId": reservation_id,
                     "paymentId": payment_id, "paymentStatus": "PAID"})
