"""Deploy only to the existing FCM/Auth Firebase project."""
import json
import os

import firebase_admin
from firebase_admin import firestore
from firebase_functions import https_fn, scheduler_fn, firestore_fn, options

from chat_core import ChatError, ChatStore
from chat_push_dispatch import forward_event

firebase_admin.initialize_app()
REGION = "asia-southeast2"
APP_CHECK = os.environ.get("CHAT_ENFORCE_APP_CHECK", "true").lower() == "true"
options.set_global_options(max_instances=10, timeout_sec=60)


def invoke(request, operation, fields):
    if not request.auth:
        raise https_fn.HttpsError(https_fn.FunctionsErrorCode.UNAUTHENTICATED, "CHAT_SESSION_REQUIRED")
    data = request.data
    if not isinstance(data, dict) or set(data) - set(fields):
        raise https_fn.HttpsError(https_fn.FunctionsErrorCode.INVALID_ARGUMENT, "INVALID_INPUT")
    try:
        return operation(ChatStore(firestore.client()), request.auth.uid,
                         request.auth.token.get("chatSessionId"), data)
    except ChatError as error:
        raise https_fn.HttpsError(https_fn.FunctionsErrorCode(error.code), error.message) from None


@https_fn.on_call(region=REGION, enforce_app_check=APP_CHECK)
def ensureBookingChat(request: https_fn.CallableRequest):
    return invoke(request, lambda s, u, t, d: s.ensure_booking(u, t, d.get("bookingId")), ["bookingId"])


@https_fn.on_call(region=REGION, enforce_app_check=APP_CHECK)
def ensureInquiryChat(request: https_fn.CallableRequest):
    return invoke(request, lambda s, u, t, d: s.ensure_inquiry(u, t, d.get("shopId"), d.get("productId")), ["shopId", "productId"])


@https_fn.on_call(region=REGION, enforce_app_check=APP_CHECK)
def sendChatMessage(request: https_fn.CallableRequest):
    return invoke(request, lambda s, u, t, d: s.send(u, t, d.get("roomId"), d.get("messageId"), d.get("text")),
                  ["roomId", "messageId", "text"])


@https_fn.on_call(region=REGION, enforce_app_check=APP_CHECK)
def markChatRead(request: https_fn.CallableRequest):
    return invoke(request, lambda s, u, t, d: s.mark_read(u, t, d.get("roomId"), d.get("messageId")), ["roomId", "messageId"])


@https_fn.on_call(region=REGION, enforce_app_check=APP_CHECK)
def getChatUnreadSummary(request: https_fn.CallableRequest):
    return invoke(request, lambda s, u, t, d: s.unread(u, t, d.get("shopId")), ["shopId"])


@firestore_fn.on_document_created(document="chatPushEvents/{eventId}", region=REGION,
                                  timeout_sec=30, max_instances=2, concurrency=4, cpu=1,
                                  preserve_external_changes=True)
def dispatchChatPushEvent(event: firestore_fn.Event):
    # Created-only: backend delivery-state updates must not invoke this function.
    # Python SDK 0.6 lacks a Firestore retry option. The release procedure must
    # set/verify the deployed v2 eventTrigger.retryPolicy after each deployment.
    data = event.data.to_dict() or {}
    state = forward_event(event.params["eventId"], data.get("createdAt"))
    print(json.dumps({"severity": "INFO", "message": "Chat push callback completed",
                      "processing": state, "diagnostic": data.get("diagnostic") is True}))


@scheduler_fn.on_schedule(schedule="every 15 minutes", region=REGION, timezone="UTC", retry_count=3)
def expireInactiveInquiries(event: scheduler_fn.ScheduledEvent):
    ChatStore(firestore.client()).expire_inquiries()
