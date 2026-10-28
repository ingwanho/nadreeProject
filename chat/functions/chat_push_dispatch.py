"""Forward only an event ID to the authenticated backend; never send FCM here."""
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests
from google.auth.transport.requests import Request
from google.oauth2 import id_token

DEFAULT_BACKEND_URL = "https://na-dree.com/internal/chat/push-events"


class BoundedRequest(Request):
    def __call__(self, *args, **kwargs):
        kwargs.setdefault("timeout", 5)
        return super().__call__(*args, **kwargs)


class CallbackError(RuntimeError):
    pass


def forward_event(event_id, created_at):
    if os.environ.get("CHAT_PUSH_FORWARD_ENABLED", "true").lower() != "true":
        return "disabled"
    if not isinstance(event_id, str) or not re.fullmatch(r"[0-9a-f]{64}", event_id):
        raise CallbackError("CHAT_PUSH_INVALID_EVENT_ID")
    if isinstance(created_at, datetime):
        created_at = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at.astimezone(timezone.utc)
        if datetime.now(timezone.utc) - created_at >= timedelta(hours=1):
            return "expired"
    else:
        raise CallbackError("CHAT_PUSH_INVALID_EVENT_TIME")
    url = os.environ.get("CHAT_PUSH_BACKEND_URL", DEFAULT_BACKEND_URL)
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != "/internal/chat/push-events"):
        raise CallbackError("CHAT_PUSH_INVALID_BACKEND_URL")
    with requests.Session() as session:
        session.trust_env = False
        try:
            token = id_token.fetch_id_token(BoundedRequest(session=session), url)
            response = session.post(url, json={"eventId": event_id}, headers={"Authorization": "Bearer " + token},
                                    timeout=(5, 15), allow_redirects=False)
        except Exception:
            # Do not expose HTTP exception strings: they can contain credentials.
            raise CallbackError("CHAT_PUSH_CALLBACK_UNAVAILABLE") from None
        if not 200 <= response.status_code < 300:
            raise CallbackError("CHAT_PUSH_CALLBACK_HTTP_" + str(response.status_code))
        try:
            result = response.json()
        except ValueError:
            raise CallbackError("CHAT_PUSH_INVALID_CALLBACK_RESPONSE") from None
        if (not isinstance(result, dict) or result.get("status") != "success"
                or result.get("processing") not in ("completed", "pending", "missing")):
            raise CallbackError("CHAT_PUSH_INVALID_CALLBACK_RESPONSE")
        return result["processing"]
