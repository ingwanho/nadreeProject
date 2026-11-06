"""Real SDK tests require an explicitly selected demo emulator; never a live project."""
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.account_deletion_data import cleanup_chat
from app.account_deletion_store import DeletionStore, digest, utc
from app.chat import admin_uid
from app.errors import Problem
from chat.functions.chat_core import ChatStore

pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST") or os.environ.get("GCLOUD_PROJECT") != "demo-nadree-chat",
    reason="requires explicit demo-nadree-chat Firestore emulator")


@pytest.fixture
def store():
    from google.cloud.firestore import Client
    from google.auth.credentials import AnonymousCredentials
    db = Client(project="demo-nadree-chat", credentials=AnonymousCredentials())
    store = object.__new__(DeletionStore)
    store.configured = True
    store.database = lambda: db
    yield store, db
    for row in list(db.collection("accountDeletionRequests").stream()):
        row.reference.delete()
    db.close()


def test_native_concurrent_acceptance_deduplicates_key_and_owner(store):
    store, _ = store
    owner = str(uuid4())
    row = {"recordType": "request", "requestId": str(uuid4()), "ownerId": owner,
           "requestState": "PROCESSING", "receiptHash": digest("secret")}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.create(row), range(4)))
    assert sum(created for _, created in results) == 1
    assert store.active(owner)["requestId"] == row["requestId"]

    def different_key(_):
        try:
            return store.create({**row, "requestId": str(uuid4())})
        except Problem as error:
            return error.code

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(different_key, range(3))) == ["DELETION_REQUEST_ALREADY_ACTIVE"] * 3


def test_finish_preserves_rotated_receipt_and_only_expired_completed_requests_are_removed(store):
    store, _ = store
    row = {"recordType": "request", "requestId": str(uuid4()), "ownerId": str(uuid4()),
           "requestState": "PROCESSING", "receiptHash": digest("old")}
    store.create(row)
    store.update(row["requestId"], {"receiptHash": digest("rotated")})
    store.finish(row, {"recordType": "request", "requestId": row["requestId"],
        "requestState": "COMPLETED", "receiptHash": row["receiptHash"], "expiresAt": utc()})
    assert store.get(row["requestId"])["receiptHash"] == digest("rotated")
    assert store.active(row["ownerId"]) is None
    assert store.remove_expired(utc()) == 1


def test_real_sdk_chat_redaction_preserves_other_party_and_sequence(store):
    _, db = store
    chat = ChatStore(db)
    ident, room = str(uuid4()), str(uuid4())
    uid = admin_uid(ident)
    ref = chat.ref("chatRoomAccess/" + room)
    ref.set({"customerUid": "isolated-customer", "shopId": "isolated-shop", "lastSequence": 2})
    own, other = ref.collection("messages").document("own"), ref.collection("messages").document("other")
    own.set({"senderUid": uid, "text": "employee text", "sequence": 1, "createdAt": utc()})
    other.set({"senderUid": "isolated-customer", "text": "test@example.com", "sequence": 2, "createdAt": utc()})
    chat.ref("chatUsers/" + uid).set({"active": False})
    assert cleanup_chat(SimpleNamespace(store=lambda: chat), ident, [{"email": "test@example.com"}]) is True
    assert own.get().to_dict()["text"] == "[Deleted]"
    assert own.get().to_dict()["sequence"] == 1
    assert other.get().to_dict()["text"] == "test@example.com"
    assert chat.ref("chatUsers/" + uid).get().to_dict() is None
    own.delete()
    other.delete()
    ref.delete()
