"""Explicit Nadree-owned field map. Shared identities are retained only with evidence."""
import secrets
import uuid

from sqlalchemy import delete, inspect, or_, select, update

from app.security import GENERAL, PRIMARY, SESSION_MARKER, now, password_hash, roles

ANONYMOUS_ADMIN = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://na-dree.com/nadree/anonymized-admin"))
ADMIN_JSON_FIELDS = {"adminId", "changedBy", "changed_by", "createdBy", "approvedByAdminId",
                     "handedOverByAdminId", "receivedByAdminId", "receiptRecoveredByAdminId"}
OWN_REFERENCES = {"MSP_VEHICLE_STATUS": "changed_by", "MSP_VEHICLE_QR_HISTORY": "changed_by",
    "MSP_RESERVATION_HISTORY": "changed_by", "MSP_RENTAL_CONTRACT_HISTORY": "changed_by",
    "MSP_RENTAL_PAYMENT": "refund_requested_by_admin_id"}


def clean_json(value, ids):
    if isinstance(value, list):
        return [clean_json(item, ids) for item in value]
    if isinstance(value, dict):
        return {name: None if (name in ADMIN_JSON_FIELDS or name == "requestedById" and
                    value.get("requestedByType") == "ADMIN") and isinstance(item, str) and item in ids
                else clean_json(item, ids) for name, item in value.items()}
    return value


def anonymous_actor(db, session):
    admins = db.table("MSP_ADMIN")
    if not session.execute(select(admins.c.admin_id).where(admins.c.admin_id == ANONYMOUS_ADMIN)).first():
        session.execute(admins.insert().values(admin_id=ANONYMOUS_ADMIN,
            login_id="nadree-anonymous-" + ANONYMOUS_ADMIN, email=None, phone=None, admin_name=None,
            password_hash=password_hash(secrets.token_urlsafe(32)), mfa_method="none", account_type="manager", is_active=0))
    return ANONYMOUS_ADMIN


def cleanup_sql(db, session, snapshot, contacts):
    ids = [member["id"] for member in snapshot["admins"]]
    id_set = set(ids)
    available = set(inspect(session.connection()).get_table_names())
    terms = [str(contact[name]).casefold() for contact in contacts for name in ("name", "email", "phoneText") if contact.get(name)]
    retained, review = [], set()
    admins, tokens, scope = (db.table(name) for name in ("MSP_ADMIN", "MSP_REFRESH_TOKEN", "MSP_ADMIN_SPOT_SCOPE"))
    pending = db.table("MSP_RENTAL_ADMIN_REQUEST")
    session.execute(update(scope).where(scope.c.granted_by.in_(ids)).values(granted_by=None))
    session.execute(delete(pending).where(pending.c.admin_id.in_(ids)))
    if session.execute(select(pending.c.request_id).where(pending.c.reviewed_by_admin_id.in_(ids)).limit(1)).first():
        actor = anonymous_actor(db, session)
        session.execute(update(pending).where(pending.c.reviewed_by_admin_id.in_(ids)).values(reviewed_by_admin_id=actor))
    for name, column in OWN_REFERENCES.items():
        if name in available:
            table = db.table(name)
            if column in table.c:
                session.execute(update(table).where(table.c[column].in_(ids)).values({column: None}))
    payments = db.table("MSP_RENTAL_PAYMENT")
    session.execute(update(payments).where(payments.c.cancellation_requested_by_type == "ADMIN",
        payments.c.cancellation_requested_by_id.in_(ids)).values(cancellation_requested_by_id=None))
    for name, column in (("MSP_RESERVATION", "required_criteria_json"), ("MSP_RESERVATION_HISTORY", "details")):
        if name not in available:
            continue
        table = db.table(name)
        pk = list(table.primary_key.columns)
        for row in session.execute(select(table)).mappings():
            value = row.get(column)
            cleaned = clean_json(value, id_set)
            if cleaned != value:
                session.execute(update(table).where(*(key == row[key.name] for key in pk)).values({column: cleaned}))
    # Unknown free text is reviewed rather than deleting another person's text
    # or claiming that arbitrary mentions have been reliably anonymized.
    for name, columns in (("MSP_RESERVATION_HISTORY", ("reason", "details")),
                          ("MSP_RENTAL_CONTRACT_HISTORY", ("reason",)),
                          ("MSP_RENTAL_PAYMENT", ("refund_reason",)),
                          ("MSP_RENTAL_VEHICLE", ("rental_memo",))):
        if name not in available:
            continue
        table = db.table(name)
        for row in session.execute(select(table)).mappings():
            if any(term in str(row.get(column) or "").casefold() for term in terms for column in columns):
                review.add(name)
    # These audit links belong to shared assets/organization records; classify
    # or remove them with the owning service instead of mutating its history.
    for name in ("MSP_VEHICLE", "MSP_ORG", "MSP_REGION", "MSP_LOCAL", "MSP_SPOT"):
        if name in available:
            table = db.table(name)
            if "created_by" in table.c and session.execute(select(table.c.created_by)
                    .where(table.c.created_by.in_(ids)).limit(1)).first():
                review.add("SHARED_ASSET_AUDIT_REFERENCES")
    for admin_id in ids:
        other_roles = roles(session, db, admin_id) - {PRIMARY, GENERAL}
        other_session = session.execute(select(tokens.c.token_id).where(tokens.c.admin_id == admin_id,
            or_(tokens.c.user_agent != SESSION_MARKER, tokens.c.user_agent.is_(None)),
            tokens.c.revoked_at.is_(None), tokens.c.expires_at > now())).first()
        session.execute(delete(tokens).where(tokens.c.admin_id == admin_id, tokens.c.user_agent == SESSION_MARKER))
        if other_roles or other_session:
            retained.append({"category": "SHARED_IDENTITY_FOR_OTHER_ACTIVE_SERVICE",
                "fields": ["sharedAdminId", "name", "email", "phone", "sharedScopes", "sharedAssetAuditReferences"],
                "purpose": "Authentication and access for another active service",
                "retentionBasis": "OTHER_ACTIVE_SERVICE_RELATIONSHIP",
                "retentionUntil": "Until the other active service relationship ends under its policy",
                "reason": "An active non-rental role or non-Nadree session was verified in SQL."})
        else:
            session.execute(delete(scope).where(scope.c.admin_id == admin_id))
            session.execute(update(admins).where(admins.c.admin_id == admin_id).values(
                login_id="deleted-" + admin_id, email=None, phone=None, admin_name=None,
                password_hash=password_hash(secrets.token_urlsafe(32)), mfa_method="none", is_active=0,
                primary_spot_master_id=None, contract_id=None, fcm_token=None, last_login_at=None))
    if snapshot["scope"] == "SUBTREE":
        spot_ids = [spot["id"] for spot in snapshot["spots"]]
        rent = db.table("MSP_SPOT_RENT")
        nullable = {name: None for name in ("contact_email", "address_detail", "directions", "introduction", "invite_code",
                                           "paypal_merchant_id", "paypal_environment") if name in rent.c}
        session.execute(update(rent).where(rent.c.spot_master_id.in_(spot_ids)).values(**nullable))
        # Business-location/history fields can also serve contracts belonging to
        # customers or another service. Keep them visible to the operator review.
        master = db.table("MSP_SPOT_MASTER")
        location = session.execute(select(master.c.address, master.c.phone).where(master.c.spot_master_id.in_(spot_ids))).all()
        if any(address or phone for address, phone in location):
            review.add("SHARED_SHOP_LOCATION_AND_CONTRACT_SNAPSHOTS")
    return retained, sorted(review)


def cleanup_chat(chat, admin_id, contacts):
    from app.chat import admin_uid
    from app.account_deletion_store import utc
    from google.cloud.firestore_v1.base_query import FieldFilter
    uid = admin_uid(admin_id)
    store, review = chat.store(), False
    terms = [str(contact[name]).casefold() for contact in contacts for name in ("name", "email", "phoneText")
             if contact.get(name)]
    for room in store.db.collection("chatRoomAccess").stream():
        messages = room.reference.collection("messages")
        owned = messages.where(filter=FieldFilter("senderUid", "==", uid))
        for message in owned.stream():
            value = message.to_dict()
            message.reference.set({"senderUid": "deleted-admin", "text": "[Deleted]",
                "sequence": value["sequence"], "createdAt": value["createdAt"]})
        for message in messages.stream():
            value = message.to_dict()
            if value.get("senderUid") != "deleted-admin" and any(term in value.get("text", "").casefold() for term in terms):
                review = True
        room.reference.collection("reads").document(uid).delete()
    for event in store.db.collection("chatPushEvents").stream():
        value = event.to_dict()
        if value.get("senderUid") == uid:
            event.reference.update({"senderUid": "deleted-admin", "inboxSynced": True, "pushPending": False,
                "pushDelivery": {"version": 1, "expiresAt": utc(), "recipients": []}})
        elif value.get("pushDelivery"):
            delivery = value["pushDelivery"]
            filtered = [item for item in delivery.get("recipients", []) if item.get("subjectId") != admin_id]
            if filtered != delivery.get("recipients", []):
                event.reference.update({"pushDelivery": {**delivery, "recipients": filtered},
                    "pushPending": any(item["status"] == "pending" for item in filtered)})
    for shop in store.db.collection("chatShops").stream():
        shop.reference.collection("members").document(uid).delete()
    for owner in store.db.collection("chatPushTokenOwners").where(filter=FieldFilter("uid", "==", uid)).stream():
        owner.reference.delete()
    store.ref("chatPushTokens/" + uid).delete()
    store.ref("chatUsers/" + uid).delete()
    return review
