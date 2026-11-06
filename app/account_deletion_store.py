"""Private deletion workflow documents in the existing FCM/Auth Firestore project."""
import hashlib
import hmac
import json
from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.errors import Problem
from app.firebase_auth import CustomerFirebaseAuth

COLLECTION = "accountDeletionRequests"
TERMINAL = {"COMPLETED", "COMPLETED_WITH_RETENTION"}


def utc(value=None):
    value = value or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def request_id(key):
    return "adr_" + digest(key)


def receipt_matches(row, secret):
    return bool(row and hmac.compare_digest(row.get("receiptHash", ""), digest(secret)))


def body_digest(body):
    return digest(json.dumps(body, sort_keys=True, separators=(",", ":")))


class DeletionStore:
    def __init__(self, settings):
        self.identity = CustomerFirebaseAuth(settings)
        self.configured = self.identity.configured

    def database(self):
        if not self.configured:
            raise Problem(503, "DELETION_NOT_CONFIGURED")
        from firebase_admin import firestore as admin_firestore
        return admin_firestore.client(app=self.identity._firebase_app())

    def ref(self, ident):
        return self.database().collection(COLLECTION).document(ident)

    def get(self, ident):
        return self.ref(ident).get().to_dict()

    def update(self, ident, values):
        self.ref(ident).update({**values, "updatedAt": utc()})

    def put(self, ident, values):
        self.ref(ident).set(values)

    def active(self, admin_id):
        if not self.configured:
            return None
        claim = self.get("owner_" + digest(admin_id))
        row = self.get(claim["requestId"]) if claim else None
        return row if row and row.get("requestState") not in TERMINAL else None

    def create(self, row):
        db = self.database()
        reference = self.ref(row["requestId"])
        claim_ref = self.ref("owner_" + digest(row["ownerId"]))

        @firestore.transactional
        def action(tx):
            existing = reference.get(transaction=tx).to_dict()
            claim = claim_ref.get(transaction=tx).to_dict()
            active = self.ref(claim["requestId"]).get(transaction=tx).to_dict() if claim else None
            if existing:
                return existing, False
            if active and active.get("requestState") not in TERMINAL:
                raise Problem(409, "DELETION_REQUEST_ALREADY_ACTIVE")
            tx.create(reference, row)
            tx.set(claim_ref, {"recordType": "owner", "requestId": row["requestId"]})
            return row, True

        return action(db.transaction())

    def records(self):
        query = self.database().collection(COLLECTION).where(filter=FieldFilter("recordType", "==", "request"))
        for snapshot in query.stream():
            yield snapshot.to_dict()

    def pending(self):
        for row in self.records():
            if row.get("requestState") not in TERMINAL:
                yield row

    def finish(self, row, values):
        db = self.database()
        claim_ref = self.ref("owner_" + digest(row["ownerId"]))
        reference = self.ref(row["requestId"])

        @firestore.transactional
        def action(tx):
            claim = claim_ref.get(transaction=tx).to_dict()
            current = reference.get(transaction=tx).to_dict() or {}
            tx.set(reference, {**values, "receiptHash": current.get("receiptHash", values["receiptHash"])})
            if claim and claim.get("requestId") == row["requestId"]:
                tx.delete(claim_ref)

        action(db.transaction())

    def remove_expired(self, at):
        query = self.database().collection(COLLECTION).where(filter=FieldFilter("expiresAt", "<=", utc(at)))
        count = 0
        for snapshot in query.stream():
            row = snapshot.to_dict()
            if row.get("requestState") in TERMINAL:
                snapshot.reference.delete()
                count += 1
        return count
