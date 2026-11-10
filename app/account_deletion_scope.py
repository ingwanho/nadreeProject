"""SQL authority and admission controls for the Firestore deletion workflow."""
import json
from contextlib import contextmanager

from sqlalchemy import or_, select, text

from app.account_deletion_store import digest
from app.errors import Problem
from app.security import GENERAL, PRIMARY, roles

READ_POSTS = {"/nadreego/vehicle/select", "/nadreego/brand", "/nadreego/booking/select",
              "/nadreego/main", "/nadreego/main/calendar", "/nadreego/vehicle/location",
              "/nadreego/vehicle/qr/validate"}


@contextmanager
def request_execution(db, ident, *, wait_seconds=0):
    """Serialize one receipt's HTTP withdrawal and background erasure."""
    if db.engine.dialect.name != "mysql":
        yield True
        return
    name = "nadree:delete:" + digest(ident)[:48]
    with db.engine.connect() as connection:
        try:
            acquired = connection.scalar(text("SELECT GET_LOCK(:name, :wait)"),
                {"name": name, "wait": wait_seconds}) == 1
        except Exception:
            connection.invalidate()
            raise
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
                except Exception:
                    # A pooled connection must not retain a lost named lock.
                    connection.invalidate()
                    raise


def gate(db, session, spot_id, *, lock=False):
    rent = db.table("MSP_SPOT_RENT")
    query = select(rent).where(rent.c.spot_master_id == spot_id)
    row = session.execute(query.with_for_update() if lock else query).mappings().first()
    return row.get("deletion_request_id") if row else None


def new_work_allowed(db, session, spot_id, *, lock=False):
    master = db.table("MSP_SPOT_MASTER")
    if lock:
        session.execute(select(master.c.spot_master_id).where(master.c.spot_master_id == spot_id)
                        .with_for_update()).first()
    if gate(db, session, spot_id, lock=lock):
        raise Problem(409, "SHOP_CLOSING")


def account_change_allowed(request, admin_id):
    store = request.app.state.deletions
    try:
        active = store.active(admin_id) if store.configured else None
    except Problem:
        raise
    except Exception:
        raise Problem(503, "DELETION_STATUS_UNAVAILABLE") from None
    if active:
        raise Problem(409, "DELETION_REQUEST_IN_PROGRESS")


def pending_scope_allowed(store, snapshot, *, request_id=None):
    """Check durable requests under capture's SQL spot locks before side effects.

    A Firestore request may exist even when its later SQL gate commit failed.
    Unrelated SELF requests in one shop may proceed independently.
    """
    if not store.configured:
        return
    admins = {member["id"] for member in snapshot["admins"]}
    spots = {spot["id"] for spot in snapshot["spots"]} if snapshot["scope"] == "SUBTREE" else set()
    try:
        for row in store.pending():
            if request_id and row["requestId"] == request_id:
                continue
            other = row["snapshot"]
            other_admins = {member["id"] for member in other["admins"]}
            other_spots = {spot["id"] for spot in other["spots"]} if other["scope"] == "SUBTREE" else set()
            if admins & other_admins or spots & other_spots:
                raise Problem(409, "DELETION_SCOPE_IN_PROGRESS")
    except Problem:
        raise
    except Exception:
        raise Problem(503, "DELETION_STATUS_UNAVAILABLE") from None


def capture(db, session, admin_id, *, lock=True):
    admins, mapping, master = (db.table(name) for name in ("MSP_ADMIN", "MSP_ADMIN_ROLE", "MSP_SPOT_MASTER"))
    account = session.execute(select(admins).where(admins.c.admin_id == admin_id)).mappings().first()
    granted = roles(session, db, admin_id) if account else set()
    if not account or not account["is_active"] or not granted & {PRIMARY, GENERAL}:
        raise Problem(403, "DELETION_NOT_AUTHORIZED")
    root_id = account.get("primary_spot_master_id")
    query = select(master).where(master.c.spot_master_id == root_id)
    root = session.execute(query.with_for_update() if lock else query).mappings().first()
    if not root:
        raise Problem(403, "SPOT_REQUIRED")
    scope = db.table("MSP_ADMIN_SPOT_SCOPE")
    if not session.execute(select(scope.c.admin_id).where(scope.c.admin_id == admin_id,
            scope.c.spot_master_id == root_id, scope.c.access_type == "manage")).first():
        raise Problem(403, "DELETION_NOT_AUTHORIZED")
    # Scope is read again after obtaining the same spot lock used by membership writes.
    current = session.execute(select(admins).where(admins.c.admin_id == admin_id)).mappings().one()
    granted = roles(session, db, admin_id)
    if not current["is_active"] or current["primary_spot_master_id"] != root_id or not granted & {PRIMARY, GENERAL}:
        raise Problem(403, "DELETION_NOT_AUTHORIZED")
    subtree = PRIMARY in granted
    condition = master.c.spot_master_id == root_id
    if subtree:
        condition = ((master.c.contract_id == root["contract_id"]) & (master.c.org_id == root["org_id"]) &
            or_(master.c.spot_master_id == root_id, master.c.unit_code.startswith(root["unit_code"] + "-", autoescape=True)))
    previous = None
    while True:
        query = select(master).where(condition).order_by(master.c.unit_code, master.c.spot_master_id)
        spots = session.execute(query.with_for_update() if lock else query).mappings().all()
        ids = [spot["spot_master_id"] for spot in spots]
        if not lock or ids == previous:
            break
        previous = ids
    query = select(admins).where(admins.c.primary_spot_master_id.in_(ids))
    if subtree:
        query = query.where(admins.c.admin_id.in_(select(mapping.c.admin_id).where(mapping.c.role_code.in_([PRIMARY, GENERAL]))))
    else:
        query = query.where(admins.c.admin_id == admin_id)
    members = session.execute(query.order_by(admins.c.admin_id).with_for_update() if lock
                              else query.order_by(admins.c.admin_id)).mappings().all()
    snapshot = {"scope": "SUBTREE" if subtree else "SELF", "rootId": root_id,
        "contractId": root["contract_id"], "companyId": root["org_id"],
        "spots": [{"id": spot["spot_master_id"], "code": spot["unit_code"],
                   "level": spot["hierarchy_level"], "active": bool(spot["is_active"])} for spot in spots],
        "admins": [{"id": member["admin_id"], "active": bool(member["is_active"]),
            "roles": sorted(session.scalars(select(mapping.c.role_code).where(
                mapping.c.admin_id == member["admin_id"], mapping.c.role_code.in_([PRIMARY, GENERAL]))))}
            for member in members]}
    return snapshot, dict(root), [dict(member) for member in members]


def scope_hash(snapshot):
    return digest(json.dumps(snapshot, sort_keys=True, separators=(",", ":")))


def outstanding(db, session, snapshot, *, external_confirmed=False):
    result = {"pendingReservations": 0, "activeRentals": 0, "pendingReturns": 0,
              "pendingRecovery": 0, "pendingRefunds": 0, "pendingExternalSettlements": 0}
    if snapshot["scope"] == "SELF":
        return result
    ids = [spot["id"] for spot in snapshot["spots"]]
    reservations, contracts, payments = (db.table(name) for name in (
        "MSP_RESERVATION", "MSP_RENTAL_CONTRACT", "MSP_RENTAL_PAYMENT"))
    rows = session.execute(select(reservations).where(reservations.c.spot_master_id.in_(ids))
                           .with_for_update()).mappings().all()
    booked = [row["reservation_id"] for row in rows]
    rentals = session.execute(select(contracts).where(contracts.c.pickup_spot_master_id.in_(ids))
                             .with_for_update()).mappings().all()
    contract_ids = [row["rental_contract_id"] for row in rentals]
    paid = session.execute(select(payments).where(or_(payments.c.reservation_id.in_(booked),
        payments.c.rental_contract_id.in_(contract_ids))).with_for_update()).mappings().all()
    result["pendingReservations"] = sum(row["reservation_status"] in ("REQUESTED", "APPROVED") for row in rows)
    result["pendingRecovery"] = sum(row["reservation_status"] == "HANDOVER_PENDING" or
        row["reservation_status"] == "EXPIRED" and row.get("handed_over_at") is not None
        and row.get("assigned_vehicle_id") is not None for row in rows)
    result["activeRentals"] = sum(row["contract_status"] in ("ON_RENT", "OVERDUE") or
        row.get("actual_start_time") is not None and row.get("actual_end_time") is None for row in rentals)
    result["pendingReturns"] = sum(row["contract_status"] == "OVERDUE" for row in rentals)
    result["pendingRefunds"] = sum(row.get("refund_status") in ("REQUESTED", "PENDING", "FAILED") or
        row.get("refund_requested_amount") is not None and
        row["refund_requested_amount"] > (row.get("refunded_amount") or 0) for row in paid)
    if not external_confirmed:
        started = {row["reservation_id"] for row in rentals if row.get("actual_start_time") is not None}
        result["pendingExternalSettlements"] = sum(row["reservation_id"] in started and
            (row.get("required_criteria_json") or {}).get("paymentMethod") != "PAYPAL" for row in rows)
        result["pendingExternalSettlements"] += sum(row.get("reservation_id") is None
            and row.get("actual_start_time") is not None and not any(
                payment.get("rental_contract_id") == row["rental_contract_id"]
                and payment.get("payment_provider") == "PAYPAL"
                and payment.get("payment_status") in ("PAID", "PARTIALLY_REFUNDED", "REFUNDED")
                for payment in paid) for row in rentals)
    return result
