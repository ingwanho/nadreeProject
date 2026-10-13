"""Real Firestore transactions against the demo emulator only, never a live project."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest

from chat.functions.chat_core import ChatError, ChatStore, utcnow

pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST") or os.environ.get("GCLOUD_PROJECT") != "demo-nadree-chat",
    reason="requires explicit demo-nadree-chat Firestore emulator")


@pytest.fixture
def chat():
    from google.cloud.firestore import Client
    from google.auth.credentials import AnonymousCredentials
    db = Client(project="demo-nadree-chat", credentials=AnonymousCredentials())
    store = ChatStore(db)
    uid, shop = str(uuid4()), str(uuid4())
    store.ref("chatUsers/" + uid).set({"active": True, "kind": "customer", "sessionId": "sid", "expiresAt": utcnow() + timedelta(hours=1)})
    store.ref("chatShops/" + shop).set({"active": True})
    yield store, uid, shop
    db.close()


def test_concurrent_inquiry_and_message_retries_are_singletons(chat):
    store, uid, shop = chat
    with ThreadPoolExecutor(max_workers=4) as pool:
        rooms = list(pool.map(lambda _: store.ensure_inquiry(uid, "sid", shop)["roomId"], range(4)))
    assert len(set(rooms)) == 1
    message = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.send(uid, "sid", rooms[0], message, "hello"), range(4)))
    assert all(result["sequence"] == 1 for result in results)
    assert store.unread(uid, "sid", shop) == {"unreadMessages": 0, "unreadRooms": 0}


def test_concurrent_bookings_consume_only_one_inquiry(chat):
    store, uid, shop = chat
    inquiry = store.ensure_inquiry(uid, "sid", shop)["roomId"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        rooms = list(pool.map(lambda booking: store.sync_booking(booking, uid, shop, "REQUESTED")["roomId"], [str(uuid4()), str(uuid4())]))
    assert len(set(rooms)) == 2
    assert rooms.count(inquiry) == 1


def test_expiry_and_committed_close_reject_new_messages(chat):
    store, uid, shop = chat
    room = store.ensure_inquiry(uid, "sid", shop)["roomId"]
    store.ref("chatRoomAccess/" + room).set({"expiresAt": utcnow() - timedelta(seconds=1)}, merge=True)
    assert store.expire_inquiries() >= 1
    assert store.ref("chatRoomAccess/" + room).get().to_dict()["status"] == "read_only"
    booking = str(uuid4())
    room = store.sync_booking(booking, uid, shop, "REQUESTED")["roomId"]
    store.block_booking(booking)
    with pytest.raises(ChatError, match="CHAT_READ_ONLY"):
        store.send(uid, "sid", room, str(uuid4()), "late")
    store.sync_booking(booking, uid, shop, "RETURNED")
    store.sync_booking(booking, uid, shop, "APPROVED")
    with pytest.raises(ChatError, match="CHAT_READ_ONLY"):
        store.send(uid, "sid", room, str(uuid4()), "reopen")


def test_admin_permissions_read_positions_and_event_deduplication(chat):
    store, uid, shop = chat
    primary, staff, outsider = [str(uuid4()) for _ in range(3)]
    for admin in (primary, staff, outsider):
        store.ref("chatUsers/" + admin).set({"active": True, "kind": "admin", "sessionId": "sid", "expiresAt": utcnow() + timedelta(hours=1)})
    for admin, can_reply in ((primary, True), (staff, False)):
        store.ref(f"chatShops/{shop}/members/{admin}").set({"active": True, "canReply": can_reply})
    booking = str(uuid4())
    room = store.sync_booking(booking, uid, shop, "REQUESTED")["roomId"]
    assert store.ensure_booking(staff, "sid", booking)["roomId"] == room
    with pytest.raises(ChatError, match="CHAT_ACCESS_DENIED"):
        store.ensure_booking(outsider, "sid", booking)
    with pytest.raises(ChatError, match="CHAT_ACCESS_DENIED"):
        store.send(staff, "sid", room, str(uuid4()), "denied")
    message = str(uuid4())
    assert store.send(primary, "sid", room, message, "reply")["sequence"] == 1
    assert store.send(primary, "sid", room, message, "reply")["sequence"] == 1
    assert store.unread(uid, "sid", shop) == {"unreadMessages": 1, "unreadRooms": 1}
    assert store.mark_read(uid, "sid", room, message) == {"position": 1}
    assert store.mark_read(uid, "sid", room, message) == {"position": 1}
    assert store.unread(uid, "sid", shop) == {"unreadMessages": 0, "unreadRooms": 0}
    from google.cloud.firestore_v1.base_query import FieldFilter
    events = list(store.db.collection("chatPushEvents").where(filter=FieldFilter("roomId", "==", room)).stream())
    assert len(events) == 1
    with pytest.raises(ChatError, match="CHAT_SESSION_REQUIRED"):
        store.unread(uid, "wrong-session", shop)
    store.ref("chatUsers/" + uid).set({"expiresAt": utcnow() - timedelta(seconds=1)}, merge=True)
    with pytest.raises(ChatError, match="CHAT_SESSION_REQUIRED"):
        store.send(uid, "sid", room, str(uuid4()), "expired")
