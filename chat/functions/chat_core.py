"""Firestore chat transactions. No client may write these documents directly."""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

TERMINAL = {"CANCELLED", "CANCELED", "REJECTED", "EXPIRED", "RETURNED"}


class ChatError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or "/" in value:
        raise ChatError("invalid-argument", "INVALID_IDENTIFIER")
    return value


def utcnow():
    return datetime.now(timezone.utc)


class ChatStore:
    def __init__(self, db):
        self.db = db

    def ref(self, path):
        return self.db.document(path)

    def read(self, tx, path):
        return self.ref(path).get(transaction=tx).to_dict()

    def run(self, fn):
        return firestore.transactional(fn)(self.db.transaction())

    def user(self, tx, uid, sid):
        user = self.read(tx, "chatUsers/" + identifier(uid))
        if not user or not user.get("active") or not sid or user.get("sessionId") != sid or user["expiresAt"] <= utcnow():
            raise ChatError("unauthenticated", "CHAT_SESSION_REQUIRED")
        return user

    def member(self, tx, uid, shop):
        member = self.read(tx, f"chatShops/{identifier(shop)}/members/{uid}")
        return member if member and member.get("active") else None

    def access(self, tx, uid, sid, room, write=False):
        user = self.user(tx, uid, sid)
        if user["kind"] == "customer" and room["customerUid"] == uid:
            allowed = True
        else:
            member = self.member(tx, uid, room["shopId"]) if user["kind"] == "admin" else None
            allowed = member and (not write or member.get("canReply"))
        if not allowed:
            raise ChatError("permission-denied", "CHAT_ACCESS_DENIED")
        if write:
            if room.get("blocked") or room["status"] != "open" or self.expired(room):
                raise ChatError("failed-precondition", "CHAT_READ_ONLY")
            if room.get("bookingId"):
                link = self.read(tx, "bookingChatAccess/" + digest(room["bookingId"]))
                if not link or link.get("blocked") or link.get("closed"):
                    raise ChatError("failed-precondition", "CHAT_READ_ONLY")
        return user

    @staticmethod
    def expired(room):
        return room["kind"] == "inquiry" and room["expiresAt"] <= utcnow()

    @staticmethod
    def room(uid, shop, booking=None):
        at = utcnow()
        return {"customerUid": uid, "shopId": shop, "bookingId": booking,
                "kind": "booking" if booking else "inquiry", "status": "open", "blocked": False,
                "createdAt": at, "updatedAt": at, "lastMessageAt": None,
                "expiresAt": None if booking else at + timedelta(hours=168),
                "lastSequence": 0, "productId": None, "productDisplayName": None}

    def ensure_inquiry(self, uid, sid, shop, product=None):
        shop = identifier(shop)
        if product is not None:
            identifier(product)
        key = "chatInquiryKeys/" + digest(uid + "\n" + shop)
        room_id = str(uuid.uuid4())
        def action(tx):
            user = self.user(tx, uid, sid)
            if user["kind"] != "customer":
                raise ChatError("permission-denied", "CUSTOMER_REQUIRED")
            shop_data = self.read(tx, "chatShops/" + shop)
            if not shop_data or not shop_data.get("active"):
                raise ChatError("not-found", "CHAT_SHOP_NOT_FOUND")
            item = self.read(tx, f"chatShops/{shop}/products/{identifier(product)}") if product else None
            if product and (not item or not item.get("active")):
                raise ChatError("not-found", "CHAT_PRODUCT_NOT_FOUND")
            link = self.read(tx, key)
            old = self.read(tx, "chatRoomAccess/" + link["roomId"]) if link else None
            if old and old["kind"] == "inquiry" and old["status"] == "open" and not self.expired(old):
                if product:
                    tx.update(self.ref("chatRoomAccess/" + link["roomId"]),
                              {"productId": product, "productDisplayName": item["displayName"]})
                return {"roomId": link["roomId"], "bookingId": None}
            if old and old["kind"] == "inquiry" and old["status"] == "open":
                tx.update(self.ref("chatRoomAccess/" + link["roomId"]), {"status": "read_only"})
            room = self.room(uid, shop)
            room.update(productId=product, productDisplayName=item["displayName"] if item else None)
            tx.set(self.ref("chatRoomAccess/" + room_id), room)
            tx.set(self.ref(key), {"roomId": room_id})
            return {"roomId": room_id, "bookingId": None}
        return self.run(action)

    def sync_booking(self, booking, uid, shop, status):
        """Trusted SQL snapshot only; terminal rooms and links never reopen."""
        identifier(booking), identifier(uid), identifier(shop)
        key = "bookingChatAccess/" + digest(booking)
        inquiry_key = "chatInquiryKeys/" + digest(uid + "\n" + shop)
        new_id = str(uuid.uuid4())
        def action(tx):
            link = self.read(tx, key)
            inquiry = self.read(tx, inquiry_key)
            old = self.read(tx, "chatRoomAccess/" + inquiry["roomId"]) if inquiry else None
            room_id = link.get("roomId") if link else None
            room = self.read(tx, "chatRoomAccess/" + room_id) if room_id else None
            closed = status in TERMINAL or bool(link and link.get("closed"))
            promoted = not room_id and not closed and old and old["kind"] == "inquiry" and old["status"] == "open" and not self.expired(old)
            if not room_id:
                room_id = inquiry["roomId"] if promoted else new_id
                room = dict(old) if promoted else self.room(uid, shop, booking)
            if room["customerUid"] != uid or room["shopId"] != shop:
                raise ChatError("failed-precondition", "BOOKING_IDENTITY_CHANGED")
            room.update(kind="booking", bookingId=booking, expiresAt=None, blocked=False,
                        status="read_only" if closed or room["status"] == "read_only" else "open", updatedAt=utcnow())
            tx.set(self.ref("chatRoomAccess/" + room_id), room)
            tx.set(self.ref(key), {"bookingId": booking, "customerUid": uid, "shopId": shop,
                                   "roomId": room_id, "closed": closed, "blocked": False})
            if promoted:
                tx.delete(self.ref(inquiry_key))
            return {"roomId": room_id, "bookingId": booking}
        return self.run(action)

    def block_booking(self, booking):
        # Called before committing SQL termination. A rollback can be reconciled;
        # a committed terminal status is made irreversible by sync_booking.
        self.ref("bookingChatAccess/" + digest(booking)).set({"blocked": True}, merge=True)

    def ensure_booking(self, uid, sid, booking):
        identifier(booking)
        def action(tx):
            link = self.read(tx, "bookingChatAccess/" + digest(booking))
            if not link or not link.get("roomId"):
                raise ChatError("failed-precondition", "BOOKING_CHAT_SYNC_PENDING")
            room = self.read(tx, "chatRoomAccess/" + link["roomId"])
            self.access(tx, uid, sid, room)
            return {"roomId": link["roomId"], "bookingId": booking}
        return self.run(action)

    def send(self, uid, sid, room_id, message_id, text):
        identifier(room_id)
        try:
            if str(uuid.UUID(message_id)) != message_id:
                raise ValueError()
            valid = isinstance(text, str) and 1 <= len(text.encode("utf-8")) <= 2000 and text.strip()
        except (ValueError, TypeError, AttributeError, UnicodeError):
            valid = False
        if not valid:
            raise ChatError("invalid-argument", "INVALID_MESSAGE")
        path = f"chatRoomAccess/{room_id}/messages/{message_id}"
        def action(tx):
            room = self.read(tx, "chatRoomAccess/" + room_id)
            if not room:
                raise ChatError("not-found", "CHAT_NOT_FOUND")
            self.access(tx, uid, sid, room)
            existing = self.read(tx, path)
            if existing:
                if existing["senderUid"] != uid or existing["text"] != text:
                    raise ChatError("already-exists", "MESSAGE_ID_CONFLICT")
                return {"messageId": message_id, "sequence": existing["sequence"]}
            user = self.access(tx, uid, sid, room, write=True)
            sequence, at = room["lastSequence"] + 1, utcnow()
            tx.create(self.ref(path), {"senderUid": uid, "text": text, "sequence": sequence, "createdAt": at})
            changes = {"lastSequence": sequence, "lastMessageAt": at, "updatedAt": at}
            if room["kind"] == "inquiry":
                changes["expiresAt"] = at + timedelta(hours=168)
            tx.update(self.ref("chatRoomAccess/" + room_id), changes)
            tx.set(self.ref(f"chatRoomAccess/{room_id}/reads/{uid}"), {"position": sequence})
            tx.create(self.ref("chatPushEvents/" + digest(room_id + ":" + message_id)),
                      {"roomId": room_id, "messageId": message_id, "shopId": room["shopId"],
                       "customerUid": room["customerUid"], "senderUid": uid, "senderKind": user["kind"],
                       "createdAt": at, "inboxSynced": False})
            return {"messageId": message_id, "sequence": sequence}
        return self.run(action)

    def mark_read(self, uid, sid, room_id, message_id):
        identifier(room_id), identifier(message_id)
        def action(tx):
            room = self.read(tx, "chatRoomAccess/" + room_id)
            if not room:
                raise ChatError("not-found", "CHAT_NOT_FOUND")
            self.access(tx, uid, sid, room)
            message = self.read(tx, f"chatRoomAccess/{room_id}/messages/{message_id}")
            if not message:
                raise ChatError("not-found", "MESSAGE_NOT_FOUND")
            path = f"chatRoomAccess/{room_id}/reads/{uid}"
            old = self.read(tx, path)
            position = max(old["position"] if old else 0, message["sequence"])
            tx.set(self.ref(path), {"position": position})
            return {"position": position}
        return self.run(action)

    def unread(self, uid, sid, shop):
        identifier(shop)
        def authorize(tx):
            user = self.user(tx, uid, sid)
            if user["kind"] == "admin" and not self.member(tx, uid, shop):
                raise ChatError("permission-denied", "CHAT_ACCESS_DENIED")
            return user
        user = self.run(authorize)
        rooms = self.db.collection("chatRoomAccess").where(filter=FieldFilter("shopId", "==", shop))
        if user["kind"] == "customer":
            rooms = rooms.where(filter=FieldFilter("customerUid", "==", uid))
        count, total = 0, 0
        for snapshot in rooms.stream():
            row = snapshot.to_dict()
            read = snapshot.reference.collection("reads").document(uid).get().to_dict()
            unread = max(0, row["lastSequence"] - (read["position"] if read else 0))
            count += unread > 0
            total += unread
        return {"unreadMessages": total, "unreadRooms": count}

    def expire_inquiries(self):
        query = self.db.collection("chatRoomAccess").where(filter=FieldFilter("kind", "==", "inquiry"))
        query = query.where(filter=FieldFilter("status", "==", "open")).where(filter=FieldFilter("expiresAt", "<=", utcnow()))
        count = 0
        for snapshot in query.limit(500).stream():
            def action(tx):
                room = snapshot.reference.get(transaction=tx).to_dict()
                if room and room["status"] == "open" and self.expired(room):
                    tx.update(snapshot.reference, {"status": "read_only"})
                    return 1
                return 0
            count += self.run(action)
        return count
