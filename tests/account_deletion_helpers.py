from copy import deepcopy
from threading import RLock

from app.account_deletion_store import DeletionStore, TERMINAL, digest, utc
from app.errors import Problem
from test_chat_retention import PurgeRef, PurgeStore, Query


class MemoryDeletionStore(DeletionStore):
    def __init__(self):
        self.configured, self.rows, self.lock = True, {}, RLock()
        self.failure = None

    def get(self, ident):
        return deepcopy(self.rows.get(ident))

    def put(self, ident, values):
        self.rows[ident] = deepcopy(values)

    def records(self):
        return (deepcopy(row) for row in list(self.rows.values()) if row.get("recordType") == "request")

    def update(self, ident, values):
        if self.failure:
            failure, self.failure = self.failure, None
            raise failure
        self.rows[ident].update(deepcopy(values))

    def active(self, admin_id):
        claim = self.get("owner_" + digest(admin_id))
        row = self.get(claim["requestId"]) if claim else None
        return row if row and row["requestState"] not in TERMINAL else None

    def create(self, row):
        with self.lock:
            if self.get(row["requestId"]):
                return self.get(row["requestId"]), False
            if self.active(row["ownerId"]):
                raise Problem(409, "DELETION_REQUEST_ALREADY_ACTIVE")
            self.rows[row["requestId"]] = deepcopy(row)
            self.rows["owner_" + digest(row["ownerId"])] = {"recordType": "owner", "requestId": row["requestId"]}
            return deepcopy(row), True

    def pending(self):
        for row in list(self.rows.values()):
            if row.get("recordType") == "request" and row["requestState"] not in TERMINAL:
                yield deepcopy(row)

    def finish(self, row, values):
        current = self.rows[row["requestId"]]
        self.rows[row["requestId"]] = {**deepcopy(values), "receiptHash": current["receiptHash"]}
        self.rows.pop("owner_" + digest(row["ownerId"]), None)

    def remove_expired(self, at):
        expired = [key for key, row in self.rows.items() if row.get("requestState") in TERMINAL
                   and row.get("expiresAt") and utc(row["expiresAt"]) <= at]
        for key in expired:
            del self.rows[key]
        return len(expired)


class PrivacyQuery(Query):
    def where(self, *, filter):
        return PrivacyQuery(self.store, self.path, filter.field_path, filter.value, self.maximum)

    def document(self, ident):
        return self.store.ref(self.path + "/" + ident)

    def stream(self):
        for snapshot in super().stream():
            value = snapshot.reference.get().to_dict()
            snapshot.to_dict = lambda value=value: deepcopy(value)
            snapshot.id = snapshot.reference.path.split("/")[-1]
            yield snapshot


class PrivacyRef(PurgeRef):
    def collection(self, name):
        return PrivacyQuery(self.db, self.path + "/" + name)

    def update(self, value):
        self.set(value, merge=True)


class PrivacyChatStore(PurgeStore):
    def document(self, path):
        return PrivacyRef(self, path)

    def collection(self, path):
        return PrivacyQuery(self, path)
