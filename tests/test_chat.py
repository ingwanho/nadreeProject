"""Isolated transactional chat logic tests; no production Firebase access."""
from copy import deepcopy
from datetime import timedelta
from threading import RLock
from uuid import uuid4

import pytest

from app.chat import admin_uid
from chat.functions.chat_core import ChatError, ChatStore, digest, utcnow


class Snapshot:
    def __init__(self, data):
        self.data = deepcopy(data)

    def to_dict(self):
        return deepcopy(self.data)


class Ref:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def get(self, transaction=None):
        if transaction:
            assert not transaction.written, "Firestore disallows reading after writing"
        return Snapshot(self.db.data.get(self.path))

    def set(self, value, merge=False):
        self.db.data[self.path] = {**(self.db.data.get(self.path, {}) if merge else {}), **deepcopy(value)}


class MemoryTransaction:
    def __init__(self):
        self.written, self.writes = False, []

    def set(self, ref, value):
        self.written = True
        self.writes.append(lambda: ref.set(value))

    def update(self, ref, value):
        self.written = True
        self.writes.append(lambda: ref.set(value, merge=True))

    def create(self, ref, value):
        assert ref.path not in ref.db.data
        self.set(ref, value)

    def delete(self, ref):
        self.written = True
        self.writes.append(lambda: ref.db.data.pop(ref.path, None))


class MemoryStore(ChatStore):
    def __init__(self):
        self.db = self
        self.data, self.lock = {}, RLock()

    def document(self, path):
        return Ref(self, path)

    def run(self, fn):
        with self.lock:
            tx = MemoryTransaction()
            result = fn(tx)
            for write in tx.writes:
                write()
            return result


@pytest.fixture
def store():
    s = MemoryStore()
    for uid, kind in [("customer", "customer"), ("other", "customer"), ("primary", "admin"), ("staff", "admin")]:
        s.ref("chatUsers/" + uid).set({"active": True, "kind": kind, "sessionId": "session", "expiresAt": utcnow() + timedelta(days=1)})
    s.ref("chatShops/shop").set({"active": True})
    s.ref("chatShops/shop/members/primary").set({"active": True, "canReply": True})
    s.ref("chatShops/shop/members/staff").set({"active": True, "canReply": False})
    s.ref("chatShops/shop/products/product").set({"active": True, "displayName": "Scooter"})
    return s


def test_inquiry_reused_and_promoted_preserving_messages_and_read_position(store):
    room = store.ensure_inquiry("customer", "session", "shop")["roomId"]
    message = str(uuid4())
    store.send("customer", "session", room, message, "hello")
    assert store.mark_read("staff", "session", room, message) == {"position": 1}
    assert store.ensure_inquiry("customer", "session", "shop", "product")["roomId"] == room
    assert store.sync_booking("booking", "customer", "shop", "REQUESTED")["roomId"] == room
    assert store.ensure_booking("staff", "session", "booking")["roomId"] == room
    assert store.data[f"chatRoomAccess/{room}/reads/staff"]["position"] == 1
    assert store.sync_booking("booking", "customer", "shop", "APPROVED")["roomId"] == room
    assert store.sync_booking("second", "customer", "shop", "REQUESTED")["roomId"] != room


def test_staff_can_read_but_cannot_reply_or_access_other_shop(store):
    room = store.sync_booking("booking", "customer", "shop", "REQUESTED")["roomId"]
    assert store.ensure_booking("staff", "session", "booking")["roomId"] == room
    with pytest.raises(ChatError, match="CHAT_ACCESS_DENIED"):
        store.send("staff", "session", room, str(uuid4()), "forbidden")
    with pytest.raises(ChatError, match="CHAT_ACCESS_DENIED"):
        store.ensure_booking("other", "session", "booking")
    other_room = store.sync_booking("other-booking", "customer", "other-shop", "REQUESTED")["roomId"]
    with pytest.raises(ChatError, match="CHAT_ACCESS_DENIED"):
        store.send("primary", "session", other_room, str(uuid4()), "forbidden")
    assert store.send("primary", "session", room, str(uuid4()), "answer")["sequence"] == 1


def test_message_idempotency_does_not_extend_expiry_or_duplicate_event(store):
    room = store.ensure_inquiry("customer", "session", "shop")["roomId"]
    ident = str(uuid4())
    first = store.send("customer", "session", room, ident, "hello")
    before = deepcopy(store.data)
    assert store.send("customer", "session", room, ident, "hello") == first
    assert store.data == before
    with pytest.raises(ChatError, match="MESSAGE_ID_CONFLICT"):
        store.send("customer", "session", room, ident, "changed")


@pytest.mark.parametrize("text", ["", " " * 3, "가" * 667, None])
def test_message_utf8_limit(store, text):
    with pytest.raises(ChatError, match="INVALID_MESSAGE"):
        store.send("customer", "session", "room", str(uuid4()), text)


def test_expiry_and_terminal_status_never_reopen(store):
    room = store.ensure_inquiry("customer", "session", "shop")["roomId"]
    store.data["chatRoomAccess/" + room]["expiresAt"] = utcnow() - timedelta(seconds=1)
    with pytest.raises(ChatError, match="CHAT_READ_ONLY"):
        store.send("customer", "session", room, str(uuid4()), "late")
    new = store.ensure_inquiry("customer", "session", "shop")["roomId"]
    assert new != room
    store.sync_booking("booking", "customer", "shop", "REQUESTED")
    store.block_booking("booking")
    with pytest.raises(ChatError, match="CHAT_READ_ONLY"):
        store.send("primary", "session", new, str(uuid4()), "late")
    store.sync_booking("booking", "customer", "shop", "CANCELLED")
    store.sync_booking("booking", "customer", "shop", "REQUESTED")
    assert store.data["chatRoomAccess/" + new]["status"] == "read_only"
    assert store.data["bookingChatAccess/" + digest("booking")]["closed"] is True


def test_revoked_or_replaced_session_is_rejected(store):
    room = store.ensure_inquiry("customer", "session", "shop")["roomId"]
    store.data["chatUsers/customer"]["sessionId"] = "new-session"
    with pytest.raises(ChatError, match="CHAT_SESSION_REQUIRED"):
        store.send("customer", "session", room, str(uuid4()), "stale")
    store.data["chatUsers/customer"]["active"] = False
    with pytest.raises(ChatError, match="CHAT_SESSION_REQUIRED"):
        store.send("customer", "new-session", room, str(uuid4()), "revoked")


def test_admin_session_api_uses_only_direct_memberships(client, setup, signin):
    class Bridge:
        def revoke(self, uid):
            pass

        def issue(self, uid, kind, subject, sid, expires, shops, reply, token):
            assert uid == admin_uid(subject) and kind == "admin" and reply
            assert [s["shopId"] for s in shops] == ["root"]
            return {"firebaseCustomToken": "test-only", "firebaseUid": uid, "managerId": subject, "shops": shops}
    setup["app"].state.chat = Bridge()
    response = client.post("/nadreego/chat/session", headers=signin())
    assert response.status_code == 200, response.text
    assert response.json()["region"] == "asia-southeast2"
    assert client.post("/nadreego/chat/session").status_code == 401


def test_chat_session_is_disabled_until_explicitly_enabled(client, signin):
    result = client.post("/nadreego/chat/session", headers=signin())
    assert result.status_code == 503
    assert result.json()["errorCode"] == "CHAT_NOT_CONFIGURED"
