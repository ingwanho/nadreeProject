import hashlib
import base64
from copy import copy
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis import RedisError
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.errors import Problem
from app.fcm import queue_payment_complete
from app.security import now

router = APIRouter(tags=["W08 PayPal webhook"])
HEADERS = ("paypal-transmission-id", "paypal-transmission-time", "paypal-transmission-sig", "paypal-cert-url", "paypal-auth-algo")
SUPPORTED = {"CHECKOUT.ORDER.APPROVED", "CHECKOUT.PAYMENT-APPROVAL.REVERSED", "PAYMENT.CAPTURE.PENDING",
    "PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DECLINED", "PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED",
    "PAYMENT.REFUND.PENDING", "PAYMENT.REFUND.FAILED"}
REFUNDS = {"PAYMENT.CAPTURE.REFUNDED", "PAYMENT.REFUND.PENDING", "PAYMENT.REFUND.FAILED"}
WEBHOOK_MAX_SKEW_SECONDS = 5 * 60
WEBHOOK_INFLIGHT_TTL_SECONDS = 30
WEBHOOK_VERIFIED_TTL_SECONDS = 15 * 60


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise Problem(500, "PAYPAL_ID_INVALID")
    return value


def amount(value):
    try:
        currency, raw = value["currency_code"], value["value"]
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency) or not isinstance(raw, str) or len(raw) > 25:
            raise ValueError
        result = Decimal(raw)
        if not result.is_finite() or result < 0 or result.as_tuple().exponent < -2:
            raise ValueError
        if currency in ("JPY", "HUF", "TWD") and result != result.to_integral_value():
            raise ValueError
        return currency, result
    except (KeyError, TypeError, InvalidOperation, ValueError):
        raise Problem(500, "PAYPAL_AMOUNT_INVALID") from None


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (AttributeError, ValueError, TypeError):
        raise Problem(500, "PAYPAL_TIME_INVALID") from None


def webhook_time_is_fresh(value, at=None):
    try:
        parsed = timestamp(value)
    except Problem:
        return False
    current = at or now()
    return abs((current - parsed).total_seconds()) <= WEBHOOK_MAX_SKEW_SECONDS


def webhook_digest(raw, headers):
    digest = hashlib.sha256()
    digest.update(raw.encode("utf-8"))
    for name in HEADERS:
        digest.update(b"\0")
        digest.update(name.encode("ascii"))
        digest.update(b"\0")
        digest.update(headers.get(name, "").encode("utf-8"))
    return digest.hexdigest()


class WebhookReplayGuard:
    """Best-effort Redis guard; the webhook DB remains the durable idempotency source."""

    def __init__(self, redis, environment):
        self.redis = redis
        self.prefix = "nadree:paypal:webhook:" + str(environment).lower() + ":"

    def begin(self, digest):
        if self.redis is None:
            return None
        try:
            if self.redis.get(self.prefix + "verified:" + digest):
                return "verified"
            if not self.redis.set(self.prefix + "inflight:" + digest, "1", nx=True,
                                  ex=WEBHOOK_INFLIGHT_TTL_SECONDS):
                return "busy"
            return "acquired"
        except (RedisError, AttributeError, TypeError):
            return None

    def mark_verified(self, digest):
        if self.redis is None:
            return
        try:
            self.redis.set(self.prefix + "verified:" + digest, "1", ex=WEBHOOK_VERIFIED_TTL_SECONDS)
        except (RedisError, AttributeError, TypeError):
            pass

    def release(self, digest):
        if self.redis is None:
            return
        try:
            self.redis.delete(self.prefix + "inflight:" + digest)
        except (RedisError, AttributeError, TypeError):
            pass


class PayPalClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.base = "https://api-m.sandbox.paypal.com" if settings.paypal_environment == "SANDBOX" else "https://api-m.paypal.com"
        self.http = httpx.Client(base_url=self.base, timeout=httpx.Timeout(10, connect=5), follow_redirects=False,
                                 transport=transport, trust_env=False)
        self.lock = Lock()
        self.token, self.expires = None, 0
        self.merchant_id = None

    def for_merchant(self, merchant_id):
        if not isinstance(merchant_id, str) or not re.fullmatch(r"[A-Z0-9]{13}", merchant_id):
            raise Problem(409, "PAYMENT_MERCHANT_RECONCILIATION_REQUIRED")
        bound = copy(self)
        bound.merchant_id = merchant_id
        return bound

    def verify_merchant(self, merchant_id):
        partner = self.settings.paypal_partner_merchant_id
        if not re.fullmatch(r"[A-Z0-9]{13}", partner):
            raise Problem(503, "PAYPAL_PARTNER_NOT_CONFIGURED")
        result = self.call("GET", "/v1/customer/partners/" + partner + "/merchant-integrations/" + identifier(merchant_id),
                           missing_code="PAYPAL_MERCHANT_NOT_READY")
        integrations = result.get("oauth_integrations") or []
        granted = any(integration.get("integration_type") == "OAUTH_THIRD_PARTY" and
                      any(item.get("partner_client_id") == self.settings.paypal_client_id.get_secret_value()
                          and {"https://uri.paypal.com/services/payments/realtimepayment",
                               "https://uri.paypal.com/services/payments/refund"}.issubset(item.get("scopes") or [])
                          for item in (integration.get("oauth_third_party") or []))
                      for integration in integrations)
        if (result.get("merchant_id") != merchant_id or result.get("payments_receivable") is not True
                or result.get("primary_email_confirmed") is not True or not granted):
            raise Problem(409, "PAYPAL_MERCHANT_NOT_READY")

    def seller_by_tracking(self, tracking):
        partner = self.settings.paypal_partner_merchant_id
        if not re.fullmatch(r"[A-Z0-9]{13}", partner):
            raise Problem(503, "PAYPAL_PARTNER_NOT_CONFIGURED")
        result = self.call("GET", "/v1/customer/partners/" + partner + "/merchant-integrations",
                           params={"tracking_id": tracking}, missing_code="PAYPAL_ONBOARDING_INCOMPLETE")
        merchant = result.get("merchant_id")
        if not isinstance(merchant, str) or not re.fullmatch(r"[A-Z0-9]{13}", merchant):
            raise Problem(409, "PAYPAL_ONBOARDING_INCOMPLETE")
        if result.get("tracking_id", tracking) != tracking:
            raise Problem(409, "PAYPAL_ONBOARDING_TRACKING_MISMATCH")
        self.verify_merchant(merchant)
        return merchant

    def onboarding_url(self, session_id, return_url, referral_path=None):
        if referral_path:
            if not referral_path.startswith("/v2/customer/partner-referrals/") or "?" in referral_path:
                raise Problem(500, "PAYPAL_REFERRAL_INVALID")
            result = self.call("GET", referral_path)
        else:
            result = self.call("POST", "/v2/customer/partner-referrals", json={
                "tracking_id": session_id,
                "partner_config_override": {"return_url": return_url},
                "operations": [{"operation": "API_INTEGRATION", "api_integration_preference": {
                    "rest_api_integration": {"integration_method": "PAYPAL", "integration_type": "THIRD_PARTY",
                        "third_party_details": {"features": ["PAYMENT", "REFUND"]}}}}],
                "products": ["EXPRESS_CHECKOUT"],
                "legal_consents": [{"type": "SHARE_DATA_CONSENT", "granted": True}]})
        links = {item.get("rel"): item.get("href") for item in result.get("links", [])}
        action, own = urlsplit(links.get("action_url") or ""), urlsplit(links.get("self") or "")
        expected_host = "www.sandbox.paypal.com" if self.settings.paypal_environment == "SANDBOX" else "www.paypal.com"
        if action.scheme != "https" or action.hostname != expected_host or action.username or action.password:
            raise Problem(500, "PAYPAL_REFERRAL_INVALID")
        if own.scheme != "https" or own.netloc != urlsplit(self.base).netloc or not own.path.startswith("/v2/customer/partner-referrals/"):
            raise Problem(500, "PAYPAL_REFERRAL_INVALID")
        return links["action_url"], own.path

    def check_configuration(self):
        s = self.settings
        if not all((s.paypal_client_id.get_secret_value(), s.paypal_client_secret.get_secret_value(),
                    s.paypal_webhook_id.get_secret_value())):
            raise Problem(500, "PAYPAL_NOT_CONFIGURED")

    def call(self, method, path, headers=None, missing_code=None, **kwargs):
        self.check_configuration()
        try:
            with self.lock:
                if self.token is None or monotonic() >= self.expires:
                    response = self.http.post("/v1/oauth2/token", auth=(self.settings.paypal_client_id.get_secret_value(),
                        self.settings.paypal_client_secret.get_secret_value()), data={"grant_type": "client_credentials"})
                    response.raise_for_status()
                    token = response.json()
                    self.token = token["access_token"]
                    self.expires = monotonic() + max(0, int(token["expires_in"]) - 30)
            request_headers = {"Authorization": "Bearer " + self.token}
            if self.settings.paypal_partner_attribution_id:
                request_headers["PayPal-Partner-Attribution-Id"] = self.settings.paypal_partner_attribution_id
            if self.merchant_id:
                def encode(value):
                    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")
                request_headers["PayPal-Auth-Assertion"] = encode({"alg": "none"}) + "." + encode({
                    "iss": self.settings.paypal_client_id.get_secret_value(), "payer_id": self.merchant_id}) + "."
            if headers:
                request_headers.update(headers)
            result = self.http.request(method, path, headers=request_headers, **kwargs)
            if result.status_code == 404 and missing_code:
                raise Problem(409, missing_code)
            result.raise_for_status()
            data = result.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise Problem(500, "PAYPAL_SERVICE_UNAVAILABLE") from None

    def verify(self, event, headers):
        response = self.call("POST", "/v1/notifications/verify-webhook-signature", json={
            "transmission_id": headers[HEADERS[0]], "transmission_time": headers[HEADERS[1]],
            "transmission_sig": headers[HEADERS[2]], "cert_url": headers[HEADERS[3]],
            "auth_algo": headers[HEADERS[4]], "webhook_id": self.settings.paypal_webhook_id.get_secret_value(),
            "webhook_event": event})
        return response.get("verification_status") == "SUCCESS"

    def get(self, kind, ident):
        if not self.merchant_id:
            raise Problem(409, "PAYMENT_MERCHANT_RECONCILIATION_REQUIRED")
        prefix = "/v2/checkout/orders/" if kind == "orders" else "/v2/payments/" + kind + "/"
        result = self.call("GET", prefix + identifier(ident))
        if result.get("id") != ident:
            raise Problem(500, "PAYPAL_RESOURCE_MISMATCH")
        return result

    def create_order(self, request_id, currency, value, reference_id):
        request_id = identifier(request_id)
        reference_id = identifier(reference_id)
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise Problem(500, "PAYPAL_AMOUNT_INVALID")
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0 or value.as_tuple().exponent < -2:
            raise Problem(500, "PAYPAL_AMOUNT_INVALID")
        body = {"intent": "CAPTURE", "purchase_units": [{
            "reference_id": reference_id, "custom_id": reference_id,
            "amount": {"currency_code": currency, "value": format(value, ".2f")}
        }]}
        if not self.merchant_id:
            raise Problem(409, "PAYMENT_MERCHANT_RECONCILIATION_REQUIRED")
        body["purchase_units"][0]["payee"] = {"merchant_id": self.merchant_id}
        return self.call("POST", "/v2/checkout/orders",
                         headers={"PayPal-Request-Id": request_id, "Prefer": "return=representation"}, json=body)

    def capture_order(self, order_id, request_id):
        if not self.merchant_id:
            raise Problem(409, "PAYMENT_MERCHANT_RECONCILIATION_REQUIRED")
        order_id = identifier(order_id)
        request_id = identifier(request_id)
        return self.call("POST", "/v2/checkout/orders/" + order_id + "/capture",
                         headers={"PayPal-Request-Id": request_id, "Prefer": "return=representation"})

    def approval_url(self, order):
        if not isinstance(order, dict):
            raise Problem(500, "PAYPAL_APPROVAL_URL_MISSING")
        hosts = {"www.sandbox.paypal.com"} if self.settings.paypal_environment == "SANDBOX" else {"www.paypal.com"}
        for link in order.get("links", []):
            if link.get("rel") != "approve" or not isinstance(link.get("href"), str):
                continue
            parsed = urlsplit(link["href"])
            if parsed.scheme == "https" and parsed.hostname in hosts and parsed.port in (None, 443) and not parsed.username and not parsed.password and not parsed.fragment:
                return link["href"]
        raise Problem(500, "PAYPAL_APPROVAL_URL_MISSING")

    def capture_reference_from_order(self, order):
        try:
            captures = order["purchase_units"][0]["payments"]["captures"]
            if len(captures) == 1 and captures[0].get("id"):
                return identifier(captures[0]["id"])
        except (KeyError, TypeError, IndexError):
            pass
        return None

    def refund(self, capture_id, request_id, currency, value):
        if not self.merchant_id:
            raise Problem(409, "PAYMENT_MERCHANT_RECONCILIATION_REQUIRED")
        capture_id = identifier(capture_id)
        request_id = identifier(request_id)
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise Problem(500, "PAYPAL_AMOUNT_INVALID")
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            raise Problem(500, "PAYPAL_AMOUNT_INVALID")
        body = {"amount": {"currency_code": currency, "value": format(value, ".2f")}}
        return self.call("POST", "/v2/payments/captures/" + capture_id + "/refund",
                         headers={"PayPal-Request-Id": request_id, "Prefer": "return=representation"}, json=body)

    def capture_reference(self, resource):
        related = resource.get("supplementary_data", {}).get("related_ids", {}).get("capture_id")
        if related:
            return identifier(related)
        hosts = {"api-m.sandbox.paypal.com", "api.sandbox.paypal.com"} if self.settings.paypal_environment == "SANDBOX" else {"api-m.paypal.com", "api.paypal.com"}
        for link in resource.get("links", []):
            url = urlsplit(link.get("href", ""))
            if link.get("rel") == "up" and url.scheme == "https" and url.hostname in hosts and url.port in (None, 443) and not url.username and not url.password:
                match = re.fullmatch(r"/v2/payments/captures/([A-Za-z0-9_-]+)", url.path)
                if match and not url.query and not url.fragment:
                    return identifier(match[1])
        raise Problem(500, "PAYPAL_CAPTURE_REFERENCE_MISSING")

    def snapshot(self, event):
        kind, resource = event["event_type"], event["resource"]
        refund = None
        if kind in REFUNDS:
            refund = self.get("refunds", resource["id"])
            if amount(refund["amount"]) != amount(resource["amount"]):
                raise Problem(500, "PAYPAL_REFUND_MISMATCH")
            capture = self.get("captures", self.capture_reference(refund))
            order_id = capture.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
            order = self.get("orders", order_id)
        elif kind.startswith("CHECKOUT."):
            order = self.get("orders", resource["id"])
            capture = None
        else:
            capture = self.get("captures", resource["id"])
            order_id = capture.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
            order = self.get("orders", order_id)
        units = order.get("purchase_units", [])
        if len(units) != 1:
            raise Problem(500, "PAYPAL_SINGLE_PAYMENT_REQUIRED")
        unit = units[0]
        captures = unit.get("payments", {}).get("captures", [])
        if len(captures) > 1:
            raise Problem(500, "PAYPAL_SINGLE_CAPTURE_REQUIRED")
        if capture is None and captures:
            capture = self.get("captures", captures[0]["id"])
        if capture and captures and captures[0]["id"] != capture["id"]:
            raise Problem(500, "PAYPAL_CAPTURE_MISMATCH")
        merchant = unit.get("payee", {}).get("merchant_id")
        if not self.merchant_id or merchant != self.merchant_id or capture and capture.get("payee", {}).get("merchant_id", merchant) != merchant:
            raise Problem(500, "PAYPAL_MERCHANT_MISMATCH")
        total = amount(unit["amount"])
        if capture and amount(capture["amount"]) != total:
            raise Problem(500, "PAYPAL_AMOUNT_MISMATCH")
        if capture and capture.get("final_capture") is False:
            raise Problem(500, "PAYPAL_SINGLE_CAPTURE_REQUIRED")
        refunds = {r["id"]: amount(r["amount"]) for r in unit.get("payments", {}).get("refunds", []) if r.get("status") == "COMPLETED"}
        if refund and refund.get("status") == "COMPLETED":
            refunds[refund["id"]] = amount(refund["amount"])
        return dict(order=order, capture=capture, refund=refund, refunds=refunds, amount=total)

    def close(self):
        self.http.close()


def save_event(db, environment, event, raw, headers, *, verification_status="SUCCESS"):
    t = db.table("MSP_PAYPAL_WEBHOOK_EVENT")
    with Session(db.engine) as session, session.begin():
        where = (t.c.payment_environment == environment) & (t.c.paypal_event_id == event["id"])
        row = session.execute(select(t).where(where)).mappings().first()
        if row:
            return dict(row)
        try:
            with session.begin_nested():
                session.execute(t.insert().values(paypal_event_id=event["id"], payment_environment=environment,
                    event_type=event["event_type"], raw_body=raw, verification_headers=headers, verification_status=verification_status,
                    processing_status="PENDING", retry_count=0, received_at=now(), updated_at=now()))
        except IntegrityError:
            pass
        return dict(session.execute(select(t).where(where)).mappings().one())


def process_event(db, client, stored, snapshot, notifier=None):
    e, p = db.table("MSP_PAYPAL_WEBHOOK_EVENT"), db.table("MSP_RENTAL_PAYMENT")
    payment_id = None
    with Session(db.engine) as session, session.begin():
        row = session.execute(select(e).where(e.c.webhook_event_id == stored["webhook_event_id"]).with_for_update()).mappings().one()
        if row["processing_status"] in ("PROCESSED", "IGNORED"):
            return
        event = json.loads(row["raw_body"])
        if event["event_type"] not in SUPPORTED:
            session.execute(update(e).where(e.c.webhook_event_id == row["webhook_event_id"]).values(processing_status="IGNORED", processed_at=now(), updated_at=now()))
            return
        order, capture = snapshot["order"], snapshot["capture"]
        payment = session.execute(select(p).where(p.c.payment_environment == row["payment_environment"],
            p.c.paypal_order_id == order["id"])).mappings().first()
        if payment is None:
            raise Problem(500, "PAYMENT_NOT_MATCHED")
        merchant = order.get("purchase_units", [{}])[0].get("payee", {}).get("merchant_id")
        if not payment.get("paypal_merchant_id") or merchant != payment["paypal_merchant_id"]:
            raise Problem(409, "PAYPAL_MERCHANT_MISMATCH")
        reservation = None
        if payment["reservation_id"]:
            reservation_table = db.table("MSP_RESERVATION")
            reservation = session.execute(select(reservation_table).where(
                reservation_table.c.reservation_id == payment["reservation_id"]).with_for_update()).mappings().first()
        # Match order/capture/cancellation lock order: reservation, then payment.
        payment = session.execute(select(p).where(p.c.payment_id == payment["payment_id"]).with_for_update()).mappings().one()
        if payment["payment_provider"] != "PAYPAL" or (payment["currency"], payment["total_price"]) != snapshot["amount"]:
            raise Problem(500, "PAYMENT_AMOUNT_MISMATCH")
        if capture and payment["paypal_capture_id"] not in (None, capture["id"]):
            raise Problem(500, "PAYMENT_CAPTURE_MISMATCH")
        if not payment["reservation_id"] and not payment["rental_contract_id"]:
            raise Problem(500, "PAYMENT_SUBJECT_INVALID")
        reservation_status = None
        if payment["reservation_id"]:
            reservation_status = reservation["reservation_status"] if reservation else None
            if reservation_status is None:
                raise Problem(500, "PAYMENT_SUBJECT_INVALID")
        if payment["rental_contract_id"]:
            c = db.table("MSP_RENTAL_CONTRACT")
            contract = session.execute(select(c).where(c.c.rental_contract_id == payment["rental_contract_id"])).mappings().first()
            if not contract or contract["reservation_id"] != payment["reservation_id"]:
                raise Problem(500, "PAYMENT_SUBJECT_INVALID")
        refunds = dict(snapshot["refunds"])
        old_refunds = session.execute(select(e.c.raw_body).where(e.c.payment_id == payment["payment_id"],
            e.c.processing_status == "PROCESSED", e.c.event_type == "PAYMENT.CAPTURE.REFUNDED")).scalars()
        for raw in old_refunds:
            refund = json.loads(raw)["resource"]
            refunds[refund["id"]] = amount(refund["amount"])
        if event["event_type"] == "PAYMENT.CAPTURE.REFUNDED" and (snapshot["refund"] or {}).get("status") != "COMPLETED":
            raise Problem(500, "REFUND_NOT_COMPLETED")
        if any(currency != payment["currency"] for currency, _ in refunds.values()):
            raise Problem(500, "REFUND_CURRENCY_MISMATCH")
        refunded = max(payment["refunded_amount"], sum((value for _, value in refunds.values()), Decimal(0)))
        status = payment["payment_status"]
        capture_status = capture.get("status") if capture else None
        if capture_status == "REFUNDED":
            refunded = payment["total_price"]
        if refunded > payment["total_price"]:
            raise Problem(500, "REFUND_AMOUNT_EXCEEDED")
        settled = capture_status in ("COMPLETED", "PARTIALLY_REFUNDED", "REFUNDED")
        if capture_status == "PARTIALLY_REFUNDED" and refunded == 0:
            raise Problem(500, "REFUND_DETAILS_UNAVAILABLE")
        if settled:
            status = "REFUNDED" if refunded == payment["total_price"] else "PARTIALLY_REFUNDED" if refunded else "PAID"
        elif payment["paid_at"] is None and status not in ("PAID", "PARTIALLY_REFUNDED", "REFUNDED", "REVERSED"):
            if capture_status in ("DECLINED", "DENIED", "FAILED") or event["event_type"] == "CHECKOUT.PAYMENT-APPROVAL.REVERSED":
                status = "FAILED"
            elif capture_status == "PENDING" or order.get("status") == "APPROVED":
                status = "PENDING"
        if payment["payment_status"] == "REVERSED" or event["event_type"] == "PAYMENT.CAPTURE.REVERSED":
            status = "REVERSED"
        values = dict(payment_status=status, refunded_amount=refunded, updated_at=now())
        refund_target = payment.get("refund_requested_amount")
        exceptional = payment.get("refund_reason") in ("LATE_CAPTURE", "DUPLICATE_CAPTURE")
        if settled and reservation:
            from app.payment_policy import payment_deadline
            from app.payment_attempts import confirmed_unpaid
            older_attempts = session.execute(select(p).where(
                p.c.reservation_id == payment["reservation_id"], p.c.payment_environment == payment["payment_environment"],
                p.c.payment_id < payment["payment_id"], p.c.paid_at.is_(None)).order_by(p.c.payment_id).with_for_update()).mappings()
            for older in older_attempts:
                if not confirmed_unpaid(client, older, terminal=True):
                    # Out-of-order webhooks must not turn the original charge into the duplicate.
                    raise Problem(503, "PAYMENT_PRIOR_ATTEMPT_UNRESOLVED")
            history = db.table("MSP_RESERVATION_HISTORY")
            events = list(session.execute(select(history).where(
                history.c.reservation_id == reservation["reservation_id"])).mappings())
            approvals = [item["created_at"] for item in events if item["event_type"] == "APPROVED"]
            terminal = [item["created_at"] for item in events if item["new_reservation_status"] in ("CANCELED", "EXPIRED")]
            captured_at = timestamp(capture["create_time"])
            deadline = payment_deadline(min(approvals) if approvals else reservation["created_at"], reservation["start_datetime"])
            late = captured_at >= deadline or bool(terminal and captured_at >= min(terminal))
            other = session.execute(select(p.c.payment_id).where(
                p.c.reservation_id == payment["reservation_id"], p.c.payment_environment == payment["payment_environment"],
                p.c.payment_id != payment["payment_id"], p.c.paid_at.is_not(None),
                (p.c.refund_reason.is_(None) | p.c.refund_reason.not_in(("LATE_CAPTURE", "DUPLICATE_CAPTURE"))))
                .with_for_update()).first()
            if late or other or exceptional:
                exceptional = True
                refund_target = payment["total_price"]
                values.update(refund_requested_amount=refund_target, refund_percentage=100,
                              refund_reason=payment["refund_reason"] if payment["refund_reason"] in ("LATE_CAPTURE", "DUPLICATE_CAPTURE") else "LATE_CAPTURE" if late else "DUPLICATE_CAPTURE",
                              refund_requested_at=payment["refund_requested_at"] or now())
            elif reservation_status == "CANCELED" and payment.get("refund_percentage") is not None:
                # A delayed webhook for a pre-cancellation capture keeps the cancellation policy.
                refund_target = (payment["total_price"] * Decimal(payment["refund_percentage"]) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                values["refund_requested_amount"] = refund_target
        refund_status = payment.get("refund_status", "NONE")
        provider_refund_status = (snapshot.get("refund") or {}).get("status")
        if provider_refund_status == "COMPLETED":
            refund_status = "COMPLETED"
        elif provider_refund_status == "PENDING":
            refund_status = "PENDING"
        elif provider_refund_status in ("FAILED", "CANCELLED"):
            refund_status = "FAILED"
        elif (capture_status == "COMPLETED" and reservation_status in ("CANCELED", "EXPIRED")
              and payment.get("refund_requested_amount") is not None
              and refunded < payment["refund_requested_amount"]
              and refund_status not in ("NOT_REQUIRED", "COMPLETED", "PENDING")):
            refund_status = "REQUESTED"
            values["refund_requested_at"] = now()
        if settled and refund_target is not None:
            if refunded >= refund_target:
                refund_status = "COMPLETED" if refund_target else "NOT_REQUIRED"
            elif refund_status not in ("PENDING", "FAILED"):
                refund_status = "REQUESTED"
        values["refund_status"] = refund_status
        if snapshot.get("refund"):
            values["paypal_refund_id"] = snapshot["refund"]["id"]
            if provider_refund_status == "COMPLETED" and refund_status == "REQUESTED" and not payment.get("refund_attempt_state"):
                # A repeated completed-refund event must not block the known remaining balance.
                values["paypal_refund_id"] = None
        if capture:
            values["paypal_capture_id"] = capture["id"]
        if settled and payment["paid_at"] is None:
            values["paid_at"] = timestamp(capture["create_time"])
        session.execute(update(p).where(p.c.payment_id == payment["payment_id"]).values(**values))
        from app.notifications import payment_notification
        if event["event_type"] in ("PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.REFUNDED", "PAYMENT.REFUND.FAILED", "PAYMENT.REFUND.PENDING"):
            payment_notification(db, session, payment, event["event_type"], "paypal:" + str(row["webhook_event_id"]))
        session.execute(update(e).where(e.c.webhook_event_id == row["webhook_event_id"]).values(payment_id=payment["payment_id"],
            processing_status="PROCESSED", last_error=None, processed_at=now(), updated_at=now(),
            retry_count=row["retry_count"] + (1 if row["processing_status"] == "FAILED" else 0)))
        if notifier and event["event_type"] == "PAYMENT.CAPTURE.COMPLETED" and settled and not exceptional and payment["reservation_id"] and reservation_status not in ("EXPIRED", "CANCELED"):
            reservation = session.execute(select(reservation_table.c.uid_token, reservation_table.c.spot_master_id).where(
                reservation_table.c.reservation_id == payment["reservation_id"])).mappings().first()
            if reservation:
                queue_payment_complete(db, session, reservation["uid_token"], payment["reservation_id"],
                                       reservation["spot_master_id"], payment["payment_id"])
        payment_id = payment["payment_id"]
        notifications = session.info.pop("fcm_notifications", [])
    if notifier and notifications:
        notifier.dispatch(db, notifications)
    return payment_id


def execute_refund(db, client, payment_id):
    from app.refund_recovery import execute_refund as recover
    return recover(db, client, payment_id)


def event_client(db, client, event):
    from app.merchant_accounts import payment_client
    resource, kind = event["resource"], event["event_type"]
    table = db.table("MSP_RENTAL_PAYMENT")
    if kind.startswith("CHECKOUT."):
        condition = table.c.paypal_order_id == resource["id"]
    elif kind in REFUNDS:
        condition = table.c.paypal_refund_id == resource["id"]
        try:
            condition = or_(condition, table.c.paypal_capture_id == client.capture_reference(resource))
        except Problem:
            pass
    else:
        condition = table.c.paypal_capture_id == resource["id"]
        order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        if order_id:
            condition = or_(condition, table.c.paypal_order_id == order_id)
    with db.engine.connect() as connection:
        payments = connection.execute(select(table).where(condition,
            table.c.payment_environment == client.settings.paypal_environment)).mappings().all()
    if len(payments) != 1:
        raise Problem(409, "PAYMENT_NOT_MATCHED")
    return payment_client(client, payments[0])


def handle_webhook(db, client, raw, event, headers, notifier=None, replay_store=None):
    stored = None
    guard = WebhookReplayGuard(replay_store, client.settings.paypal_environment)
    digest = webhook_digest(raw, headers)
    guard_state = None
    try:
        if not webhook_time_is_fresh(headers.get(HEADERS[1], "")):
            return 400
        guard_state = guard.begin(digest)
        if guard_state == "busy":
            return 503
        if guard_state != "verified" and not client.verify(event, headers):
            return 401
        if guard_state != "verified":
            guard.mark_verified(digest)
        stored = save_event(db, client.settings.paypal_environment, event, raw, headers)
        if stored["processing_status"] in ("PROCESSED", "IGNORED"):
            return 200
        persisted_event = json.loads(stored["raw_body"])
        if persisted_event["event_type"] in ("MERCHANT.ONBOARDING.COMPLETED", "MERCHANT.PARTNER-CONSENT.REVOKED"):
            from app.paypal_onboarding import process_merchant_event
            process_merchant_event(db, client, stored, persisted_event)
            return 200
        snapshot = event_client(db, client, persisted_event).snapshot(persisted_event) if persisted_event["event_type"] in SUPPORTED else None
        payment_id = process_event(db, client, stored, snapshot, notifier)
        if payment_id and persisted_event["event_type"] == "PAYMENT.CAPTURE.COMPLETED":
            execute_refund(db, client, payment_id)
        return 200
    except (Problem, SQLAlchemyError, KeyError, TypeError, ValueError) as exc:
        if stored:
            try:
                e = db.table("MSP_PAYPAL_WEBHOOK_EVENT")
                with db.engine.begin() as conn:
                    conn.execute(update(e).where(e.c.webhook_event_id == stored["webhook_event_id"],
                        e.c.processing_status.not_in(["PROCESSED", "IGNORED"])).values(processing_status="FAILED",
                        last_error=exc.code if isinstance(exc, Problem) else "PAYPAL_PROCESSING_FAILED", updated_at=now()))
            except (SQLAlchemyError, Problem):
                pass
        return 500
    finally:
        if guard_state == "acquired":
            guard.release(digest)


@router.post("/nadreego/paypal/webhook")
async def webhook(request: Request):
    headers = {name: request.headers.get(name, "") for name in HEADERS}
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json" or not all(headers.values()) or any(len(v) > 8192 for v in headers.values()):
        return JSONResponse({"status": False}, status_code=400)
    if not webhook_time_is_fresh(headers[HEADERS[1]]):
        return JSONResponse({"status": False}, status_code=400)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            return JSONResponse({"status": False}, status_code=400)
    try:
        raw = body.decode("utf-8")
        event = json.loads(raw)
        if not isinstance(event, dict) or not isinstance(event.get("resource"), dict):
            raise ValueError
        identifier(event["id"])
        identifier(event["resource"]["id"])
        timestamp(event["create_time"])
        if not all(isinstance(event.get(k), str) and 0 < len(event[k]) <= 100 for k in ("event_type", "resource_type")):
            raise ValueError
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, Problem):
        return JSONResponse({"status": False}, status_code=400)
    status = await run_in_threadpool(handle_webhook, request.app.state.db, request.app.state.paypal, raw, event, headers,
                                     request.app.state.fcm, getattr(request.app.state.limiter, "redis", None))
    return JSONResponse({"status": status == 200}, status_code=status)
