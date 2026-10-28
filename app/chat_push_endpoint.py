"""Google service identity authentication for the Firestore push callback only."""
import requests
from cachecontrol import CacheControl
from fastapi import APIRouter, Depends, Request
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from pydantic import Field
from typing import Annotated

from app.chat_push import dispatch_event
from app.errors import Problem
from app.schemas import Body

router = APIRouter(include_in_schema=False)


class CertificateRequest(GoogleRequest):
    def __call__(self, *args, **kwargs):
        kwargs.setdefault("timeout", 5)
        return super().__call__(*args, **kwargs)


class GooglePushIdentity:
    def __init__(self, settings):
        self.settings = settings
        self.session = CacheControl(requests.Session())
        self.request = CertificateRequest(session=self.session)

    def verify(self, authorization):
        if not authorization or len(authorization) > 16384:
            raise Problem(401, "AUTH_REQUIRED")
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise Problem(401, "AUTH_REQUIRED")
        settings = self.settings
        if not (settings.chat_push_audience and settings.chat_push_invoker_email and settings.chat_push_invoker_subject):
            raise Problem(503, "CHAT_PUSH_NOT_CONFIGURED")
        try:
            claims = id_token.verify_oauth2_token(parts[1], self.request, audience=settings.chat_push_audience)
        except TransportError:
            raise Problem(503, "CHAT_PUSH_AUTH_UNAVAILABLE") from None
        except (GoogleAuthError, ValueError, TypeError):
            raise Problem(401, "INVALID_SERVICE_TOKEN") from None
        if (claims.get("email") != settings.chat_push_invoker_email or claims.get("email_verified") is not True
                or claims.get("sub") != settings.chat_push_invoker_subject):
            raise Problem(403, "CHAT_PUSH_CALLER_DENIED")

    def close(self):
        self.session.close()


def require_push_identity(request: Request):
    request.app.state.chat_push_identity.verify(request.headers.get("Authorization"))


class ChatPushEvent(Body):
    eventId: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


@router.post("/internal/chat/push-events", dependencies=[Depends(require_push_identity)])
def push_event(body: ChatPushEvent, request: Request):
    if not request.app.state.settings.fcm_chat_enabled:
        raise Problem(503, "CHAT_NOT_CONFIGURED")
    try:
        state = dispatch_event(request.app.state.db, request.app.state.chat, request.app.state.fcm, body.eventId)
    except Problem:
        raise
    except Exception:
        raise Problem(503, "CHAT_PUSH_PROCESSING_DEFERRED") from None
    if state == "busy":
        raise Problem(503, "CHAT_PUSH_BUSY")
    # A pending result has durable retry state and is picked up every 30 seconds.
    return {"status": "success", "processing": state}
