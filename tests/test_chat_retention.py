"""Disposable SQL plus transactional Firestore fake; no live deletion or push."""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.chat_retention import run
from app.errors import Problem
from app.rental_schema import metadata
from chat.functions.chat_core import ChatError, digest, utcnow
from test_chat import MemoryStore, Ref


class Query:
    def __init__(self, store, path, field=None, value=None, maximum=10000):
        self.store, self.path = store, path
        self.field, self.value, self.maximum = field, value, maximum

    def where(self, *, filter):
        return Query(self.store, self.path, filter.field_path, filter.value, self.maximum)

    def limit(self, maximum):
        return Query(self.store, self.path, self.field, self.value, maximum)

    def stream(self):
        paths = sorted(path for path, value in self.store.data.items()
                       if path.startswith(self.path + "/") and path.count("/") == self.path.count("/") + 1
                       and (self.field is None or value.get(self.field) == self.value))
        return iter(SimpleNamespace(reference=self.store.ref(path)) for path in paths[:self.maximum])


class PurgeRef(Ref):
    def collection(self, name):
        return Query(self.db, self.path + "/" + name)

    def delete(self):
        self.db.data.pop(self.path, None)


class Batch:
    def __init__(self, store):
        self.store, self.references = store, []

    def delete(self, reference):
        self.references.append(reference)

    def commit(self):
        if self.store.fail_after is not None:
            if self.store.fail_after == 0:
                self.store.fail_after = None
                raise RuntimeError("isolated batch failure")
            self.store.fail_after -= 1
        self.store.batch_sizes.append(len(self.references))
        for reference in self.references:
            reference.delete()


class PurgeStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.fail_after, self.batch_sizes = None, []

    def document(self, path):
        return PurgeRef(self, path)

    def collection(self, path):
        return Query(self, path)

    def batch(self):
        return Batch(self)


def room(store, booking="booking"):
    store.ref("chatUsers/customer").set({"active": True, "kind": "customer", "sessionId": "sid",
                                         "expiresAt": utcnow() + timedelta(days=1)})
    store.ref("chatUsers/other").set({"active": True, "kind": "customer", "sessionId": "sid",
                                      "expiresAt": utcnow() + timedelta(days=1)})
    store.ref("chatShops/root").set({"active": True})
    ident = store.sync_booking(booking, "customer", "root", "APPROVED")["roomId"]
    store.send("customer", "sid", ident, str(uuid4()), "retention test message")
    store.sync_booking(booking, "customer", "root", "RETURNED")
    return ident


@pytest.fixture
def retention(setup):
    metadata.create_all(setup["engine"])
    at, store = datetime(2026, 11, 6, 4, 0), PurgeStore()
    chat = SimpleNamespace(settings=SimpleNamespace(fcm_chat_enabled=True), store=lambda: store)
    reservations, contracts = setup["db"].table("MSP_RESERVATION"), setup["db"].table("MSP_RENTAL_CONTRACT")

    def add(ident, *, ended=None, status="RETURNED", reservation_status="RETURNED"):
        before = at - timedelta(days=130)
        with setup["engine"].begin() as connection:
            connection.execute(reservations.insert().values(reservation_id=ident, uid_token="customer",
                spot_master_id="root", model_id="model", start_datetime=before,
                end_datetime=before + timedelta(days=2), reservation_status=reservation_status,
                created_at=before, updated_at=before))
            connection.execute(contracts.insert().values(rental_contract_id="contract-" + ident,
                reservation_id=ident, vehicle_id="vehicle", uid_token="customer", pickup_spot_master_id="root",
                actual_start_time=before, actual_end_time=ended, contract_status=status,
                planned_end_date=at.date(), created_at=before, updated_at=before))
        return room(store, ident)

    return {**setup, "at": at, "store": store, "chat": chat, "add": add}


def test_plan_is_sql_only_and_does_not_touch_chat(retention):
    ctx = retention
    ctx["add"]("old", ended=ctx["at"] - timedelta(days=90))
    before = deepcopy(ctx["store"].data)
    ctx["chat"].store = lambda: pytest.fail("plan must not access Firebase")
    result = run(ctx["db"], ctx["chat"], at=ctx["at"])
    assert result == {"mode": "plan", "cutoffUtc": "2026-08-08T04:00:00", "eligibleRentals": 1}
    assert ctx["store"].data == before


@pytest.mark.parametrize("status,reservation_status,age,has_end,expected", [
    ("RETURNED", "RETURNED", timedelta(days=90), True, 1),
    ("RETURNED", "RETURNED", timedelta(days=90, microseconds=-1), True, 0),
    ("RETURNED", "RETURNED", timedelta(days=91), True, 1),
    ("RETURNED", "RETURNED", timedelta(days=1), True, 0),
    ("RETURNED", "RETURNED", timedelta(days=100), False, 0),
    ("ON_RENT", "HANDED_OVER", timedelta(days=100), True, 0),
    ("OVERDUE", "HANDED_OVER", timedelta(days=100), False, 0),
    ("CANCELED", "CANCELED", timedelta(days=100), True, 0),
    ("RETURNED", "EXPIRED", timedelta(days=100), True, 0),
])
def test_eligibility_uses_completed_actual_return_not_planned_date(retention, status, reservation_status,
                                                                 age, has_end, expected):
    ctx = retention
    ctx["add"]("candidate", ended=ctx["at"] - age if has_end else None,
               status=status, reservation_status=reservation_status)
    assert run(ctx["db"], ctx["chat"], at=ctx["at"])["eligibleRentals"] == expected


def test_apply_deletes_content_but_preserves_sql_and_other_chats(retention):
    ctx, store = retention, retention["store"]
    target = ctx["add"]("old", ended=ctx["at"] - timedelta(days=91))
    keep = ctx["add"]("recent", ended=ctx["at"] - timedelta(days=1))
    inquiry = store.ensure_inquiry("customer", "sid", "root")["roomId"]
    before = deepcopy(store.data)
    names = ("MSP_RESERVATION", "MSP_RENTAL_CONTRACT", "MSP_RENTAL_PAYMENT", "MSP_RESERVATION_HISTORY")
    with ctx["engine"].connect() as connection:
        sql_before = {name: connection.execute(select(ctx["db"].table(name))).mappings().all() for name in names}
    result = run(ctx["db"], ctx["chat"], apply=True, at=ctx["at"])
    assert result["deleted"] == 1 and result["failed"] == 0
    assert not any(path.startswith("chatRoomAccess/" + target) for path in store.data)
    assert not any(value.get("roomId") == target for path, value in store.data.items() if path.startswith("chatPushEvents/"))
    assert {path: value for path, value in store.data.items() if path.startswith("chatRoomAccess/" + keep)} == {
        path: value for path, value in before.items() if path.startswith("chatRoomAccess/" + keep)}
    assert store.data["chatRoomAccess/" + inquiry] == before["chatRoomAccess/" + inquiry]
    assert store.data["chatUsers/customer"] == before["chatUsers/customer"]
    with ctx["engine"].connect() as connection:
        assert {name: connection.execute(select(ctx["db"].table(name))).mappings().all() for name in names} == sql_before
    assert run(ctx["db"], ctx["chat"], apply=True, at=ctx["at"])["alreadyDeleted"] == 1


def test_purged_booking_cannot_reappear_or_consume_new_inquiry():
    store = PurgeStore()
    ident = room(store)
    assert store.purge_booking("booking", "customer", "root") == "deleted"
    inquiry = store.ensure_inquiry("customer", "sid", "root")["roomId"]
    before = deepcopy(store.data)
    for status in ("RETURNED", "APPROVED", "REQUESTED"):
        assert store.sync_booking("booking", "customer", "root", status) == {"roomId": None, "bookingId": "booking"}
    assert store.data == before and "chatRoomAccess/" + inquiry in store.data
    with pytest.raises(ChatError, match="CHAT_NOT_FOUND"):
        store.ensure_booking("customer", "sid", "booking")
    with pytest.raises(ChatError, match="CHAT_ACCESS_DENIED"):
        store.ensure_booking("other", "sid", "booking")
    with pytest.raises(ChatError, match="CHAT_SESSION_REQUIRED"):
        store.ensure_booking("customer", "invalid", "booking")
    assert "chatRoomAccess/" + ident not in store.data


def test_partial_delete_is_fenced_chunked_and_resumes_without_recreation():
    store = PurgeStore()
    ident = room(store)
    for index in range(550):
        store.ref(f"chatRoomAccess/{ident}/messages/extra-{index:04}").set({"text": "private"})
    store.fail_after = 1
    with pytest.raises(RuntimeError, match="isolated batch failure"):
        store.purge_booking("booking", "customer", "root")
    assert "chatRoomAccess/" + ident not in store.data
    assert any(path.startswith(f"chatRoomAccess/{ident}/messages/") for path in store.data)
    assert store.ref("bookingChatAccess/" + digest("booking")).get().to_dict()["retentionDeletingAt"]
    assert store.sync_booking("booking", "customer", "root", "RETURNED")["roomId"] is None
    with pytest.raises(ChatError, match="CHAT_NOT_FOUND"):
        store.send("customer", "sid", ident, str(uuid4()), "late")
    with pytest.raises(ChatError, match="CHAT_NOT_FOUND"):
        store.mark_read("customer", "sid", ident, "extra-0500")
    assert store.purge_booking("booking", "customer", "root") == "deleted"
    assert not any(path.startswith("chatRoomAccess/" + ident) for path in store.data)
    assert max(store.batch_sizes) <= 200


def test_missing_room_gets_a_content_free_tombstone():
    store = PurgeStore()
    assert store.purge_booking("old", "customer", "root") == "noRoom"
    assert store.sync_booking("old", "customer", "root", "RETURNED")["roomId"] is None
    marker = store.ref("bookingChatAccess/" + digest("old")).get().to_dict()
    assert set(marker) == {"bookingId", "customerUid", "shopId", "roomId", "closed", "blocked", "retentionDeletedAt"}


@pytest.mark.parametrize("bad_link", [True, False])
def test_identity_mismatch_does_not_delete_any_content(bad_link):
    store = PurgeStore()
    ident = room(store)
    path = "bookingChatAccess/" + digest("booking") if bad_link else "chatRoomAccess/" + ident
    store.ref(path).set({"customerUid": "other"}, merge=True)
    before = deepcopy(store.data)
    with pytest.raises(ChatError, match="BOOKING_IDENTITY_CHANGED"):
        store.purge_booking("booking", "customer", "root")
    assert store.data == before


def test_failed_rental_is_retried_next_run_and_does_not_block_other_rentals(retention):
    ctx = retention
    ctx["add"]("a", ended=ctx["at"] - timedelta(days=91))
    ctx["add"]("b", ended=ctx["at"] - timedelta(days=91))
    ctx["store"].fail_after = 0
    first = run(ctx["db"], ctx["chat"], apply=True, at=ctx["at"])
    assert first["failed"] == 1 and first["deleted"] == 1
    second = run(ctx["db"], ctx["chat"], apply=True, at=ctx["at"])
    assert second["failed"] == 0 and second["deleted"] == 1 and second["alreadyDeleted"] == 1


def test_apply_requires_the_chat_project_to_be_enabled(retention):
    ctx = retention
    ctx["chat"].settings.fcm_chat_enabled = False
    with pytest.raises(Problem) as error:
        run(ctx["db"], ctx["chat"], apply=True, at=ctx["at"])
    assert error.value.code == "CHAT_NOT_CONFIGURED"
