"""Callable business handlers with synthetic auth and a demo Firestore emulator.

This deliberately excludes the HTTP Auth/App Check envelope. Never run against
a live Firebase project; no Admin SDK credentials or push provider are used.
"""
import os
import sys
from inspect import unwrap
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

assert os.environ.get("GCLOUD_PROJECT") == "demo-nadree-chat"
assert os.environ.get("FIRESTORE_EMULATOR_HOST") == "127.0.0.1:18080"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functions"))

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client
from firebase_functions import https_fn
import main
from chat_core import ChatStore, utcnow

db = Client(project="demo-nadree-chat", credentials=AnonymousCredentials())
main.firestore.client = lambda: db
store = ChatStore(db)
customer, primary, staff, outsider, shop = [str(uuid4()) for _ in range(5)]
for uid, kind in ((customer, "customer"), (primary, "admin"), (staff, "admin"), (outsider, "admin")):
    store.ref("chatUsers/" + uid).set({"kind": kind, "active": True, "sessionId": "session", "expiresAt": utcnow() + timedelta(hours=1)})
store.ref("chatShops/" + shop).set({"active": True})
for uid, can_reply in ((primary, True), (staff, False)):
    store.ref(f"chatShops/{shop}/members/{uid}").set({"active": True, "canReply": can_reply})

def call(handler, uid, data, sid="session"):
    request = SimpleNamespace(data=data, auth=SimpleNamespace(uid=uid, token={"chatSessionId": sid}) if uid else None)
    return unwrap(handler)(request)

def reject(handler, uid, data, code, sid="session"):
    try:
        call(handler, uid, data, sid)
    except https_fn.HttpsError as error:
        assert error.code == code
    else:
        raise AssertionError("Expected callable rejection")

try:
    room = call(main.ensureInquiryChat, customer, {"shopId": shop})["roomId"]
    assert call(main.ensureInquiryChat, customer, {"shopId": shop})["roomId"] == room
    booking = str(uuid4())
    assert store.sync_booking(booking, customer, shop, "REQUESTED")["roomId"] == room
    assert call(main.ensureBookingChat, customer, {"bookingId": booking})["roomId"] == room
    assert call(main.ensureBookingChat, staff, {"bookingId": booking})["roomId"] == room
    message = str(uuid4())
    payload = {"roomId": room, "messageId": message, "text": "emulator message"}
    assert call(main.sendChatMessage, primary, payload)["sequence"] == 1
    assert call(main.sendChatMessage, primary, payload)["sequence"] == 1
    assert call(main.getChatUnreadSummary, customer, {"shopId": shop}) == {"unreadMessages": 1, "unreadRooms": 1}
    assert call(main.markChatRead, customer, {"roomId": room, "messageId": message}) == {"position": 1}
    assert call(main.getChatUnreadSummary, customer, {"shopId": shop}) == {"unreadMessages": 0, "unreadRooms": 0}
    reject(main.sendChatMessage, staff, {**payload, "messageId": str(uuid4())}, https_fn.FunctionsErrorCode.PERMISSION_DENIED)
    reject(main.ensureBookingChat, outsider, {"bookingId": booking}, https_fn.FunctionsErrorCode.PERMISSION_DENIED)
    reject(main.ensureInquiryChat, None, {"shopId": shop}, https_fn.FunctionsErrorCode.UNAUTHENTICATED)
    reject(main.ensureInquiryChat, customer, {"shopId": shop, "extra": True}, https_fn.FunctionsErrorCode.INVALID_ARGUMENT)
    reject(main.sendChatMessage, customer, {**payload, "text": ""}, https_fn.FunctionsErrorCode.INVALID_ARGUMENT)
    reject(main.getChatUnreadSummary, customer, {"shopId": shop}, https_fn.FunctionsErrorCode.UNAUTHENTICATED, sid="expired-session")
    inquiry = call(main.ensureInquiryChat, customer, {"shopId": shop})["roomId"]
    store.ref("chatRoomAccess/" + inquiry).set({"expiresAt": utcnow() - timedelta(seconds=1)}, merge=True)
    unwrap(main.expireInactiveInquiries)(None)
    assert store.ref("chatRoomAccess/" + inquiry).get().to_dict()["status"] == "read_only"
    print("CALLABLE_BUSINESS_EMULATOR PASS: five callable handlers and expiry scheduler; permissions, read positions, idempotency, missing/session auth, invalid input")
finally:
    db.close()
