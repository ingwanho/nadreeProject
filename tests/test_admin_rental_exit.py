from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.security import PRIMARY, now
from test_account_deletions import privacy, process, submit
from test_pending_reservation_approval import pending_bookings


def approve(ctx, headers, ident):
    result = ctx["client"].post("/nadreego/booking/action", headers=headers,
        json={"bookedNo": "BO" + ident, "action": "APPROVE"})
    assert result.status_code == 200, result.text


def live_rental(ctx, ident):
    reservation, contract = ctx["db"].table("MSP_RESERVATION"), ctx["db"].table("MSP_RENTAL_CONTRACT")
    at = now() - timedelta(hours=1)
    with ctx["engine"].begin() as conn:
        row = conn.execute(select(reservation).where(reservation.c.reservation_id == ident)).mappings().one()
        conn.execute(update(reservation).where(reservation.c.reservation_id == ident).values(
            reservation_status="HANDED_OVER", vehicle_assignment_status="LOCKED", handed_over_at=at))
        conn.execute(contract.insert().values(rental_contract_id="rental-" + ident, reservation_id=ident,
            uid_token=row["uid_token"], vehicle_id=row["assigned_vehicle_id"], pickup_spot_master_id="root",
            actual_start_time=at, planned_end_date=(at + timedelta(days=3)).date(), contract_status="ON_RENT",
            created_at=at, updated_at=at))
        state = ctx["db"].table("MSP_VEHICLE_STATUS")
        conn.execute(update(state).where(state.c.vehicle_id == row["assigned_vehicle_id"]).values(status="ON_RENT"))
        # Another staff member can physically hand over a booking approved by
        # the departing staff member; approval still determines responsibility.
        conn.execute(ctx["db"].table("MSP_RESERVATION_HISTORY").insert().values(
            reservation_id=ident, event_type="HANDOVER_PENDING", previous_reservation_status="APPROVED",
            new_reservation_status="HANDOVER_PENDING", changed_by="general2", created_at=now()))
    return row["assigned_vehicle_id"]


def snapshot(ctx):
    names = ("MSP_RESERVATION", "MSP_RENTAL_CONTRACT", "MSP_RENTAL_PAYMENT", "MSP_VEHICLE_STATUS", "MSP_SPOT_MASTER")
    with ctx["engine"].connect() as conn:
        return {name: [dict(row) for row in conn.execute(select(ctx["db"].table(name))).mappings()] for name in names}


@pytest.mark.parametrize("flow", ["legacy", "privacy", "staff-removal"])
def test_general_transfers_own_approved_bookings_and_live_rentals_without_canceling_any_data(privacy, pending_bookings, signin, flow):
    ctx = privacy
    _, book = pending_bookings
    general, primary = signin("general"), signin()
    ids = [book(i)["reservationId"] for i in range(3)]
    book(3, offset=10)  # Unapproved shared request has no assigned approving manager.
    approve(ctx, general, ids[0])
    approve(ctx, general, ids[1])
    approve(ctx, primary, ids[2])
    live_rental(ctx, ids[0])
    payments = ctx["db"].table("MSP_RENTAL_PAYMENT")
    with ctx["engine"].begin() as conn:
        conn.execute(payments.insert().values(reservation_id=ids[0], payment_provider="PAYPAL", payment_environment="SANDBOX",
            payment_status="PAID", paypal_capture_id="isolated-existing-capture", total_price=30,
            currency="USD", paid_at=now(), created_at=now(), updated_at=now()))
    before = snapshot(ctx)
    if flow == "privacy":
        accepted, _, _, _ = submit(ctx, general)
        assert accepted.status_code == 202
        assert process(ctx)["completed"] == 1
    elif flow == "legacy":
        result = ctx["client"].delete("/nadreego/admin/account", headers=general)
        assert result.status_code == 200, result.text
    else:
        result = ctx["client"].post("/nadreego/shop/adminDelete", headers=primary, json={"adminId": "general"})
        assert result.status_code == 200, result.text
    assert snapshot(ctx) == before
    history, rentals = ctx["db"].table("MSP_RESERVATION_HISTORY"), ctx["db"].table("MSP_RENTAL_CONTRACT_HISTORY")
    with ctx["engine"].connect() as conn:
        moved = list(conn.execute(select(history).where(history.c.event_type == "MANAGER_TRANSFERRED")).mappings())
        assert {row["reservation_id"] for row in moved} == set(ids[:2])
        assert {row["changed_by"] for row in moved} == {"primary"}
        assert conn.scalar(select(func.count()).select_from(rentals).where(rentals.c.event_type == "MANAGER_TRANSFERRED")) == 1
        assert conn.scalar(select(func.count()).select_from(history).where(history.c.event_type == "CANCELLED")) == 0
    notices = ctx["client"].get("/nadreego/notifications?shopId=root", headers=primary)
    assert notices.status_code == 200
    assert sum(item["eventType"] == "RESERVATION_MANAGER_TRANSFERRED" for item in notices.json()["items"]) == 2
    assert ctx["client"].get("/nadreego/shop/admin", headers=general).status_code == 401
    assert ctx["client"].get("/nadreego/shop/admin", headers=primary).status_code == 200
    if flow == "privacy":
        assert process(ctx)["processed"] == 0


@pytest.mark.parametrize("flow", ["legacy", "privacy", "staff-removal"])
@pytest.mark.parametrize("status,has_end,transferred", [
    ("RETURNED", False, True),
    ("ON_RENT", True, True),
    ("RETURNED", True, False),
])
def test_general_transfers_until_contract_status_and_actual_return_both_confirm_completion(
        privacy, pending_bookings, signin, flow, status, has_end, transferred):
    ctx = privacy
    _, book = pending_bookings
    general, primary = signin("general"), signin()
    ident = book(0)["reservationId"]
    approve(ctx, general, ident)
    live_rental(ctx, ident)
    contracts = ctx["db"].table("MSP_RENTAL_CONTRACT")
    with ctx["engine"].begin() as conn:
        # Keep the reservation snapshot unchanged: neither contract field alone
        # proves completion, while an actually returned contract needs no transfer.
        conn.execute(update(contracts).where(contracts.c.reservation_id == ident).values(
            contract_status=status, actual_end_time=now() - timedelta(minutes=30) if has_end else None))
    before = snapshot(ctx)

    if flow == "privacy":
        accepted, _, _, _ = submit(ctx, general)
        assert accepted.status_code == 202
        assert process(ctx)["completed"] == 1
    elif flow == "legacy":
        result = ctx["client"].delete("/nadreego/admin/account", headers=general)
        assert result.status_code == 200, result.text
    else:
        result = ctx["client"].post("/nadreego/shop/adminDelete", headers=primary, json={"adminId": "general"})
        assert result.status_code == 200, result.text

    assert snapshot(ctx) == before
    with ctx["engine"].connect() as conn:
        for name in ("MSP_RESERVATION_HISTORY", "MSP_RENTAL_CONTRACT_HISTORY"):
            history = ctx["db"].table(name)
            moved = list(conn.execute(select(history).where(history.c.event_type == "MANAGER_TRANSFERRED")).mappings())
            assert len(moved) == int(transferred)
            assert {row["changed_by"] for row in moved} == ({"primary"} if transferred else set())
        notices = ctx["db"].table("MSP_RENTAL_NOTIFICATION")
        assert conn.scalar(select(func.count()).select_from(notices).where(
            notices.c.event_type == "RESERVATION_MANAGER_TRANSFERRED", notices.c.target_id == ident)) == int(transferred)
    assert ctx["client"].get("/nadreego/shop/admin", headers=general).status_code == 401
    assert ctx["client"].get("/nadreego/shop/admin", headers=primary).status_code == 200


def test_missing_primary_keeps_account_and_work_unchanged(privacy, pending_bookings, signin):
    ctx = privacy
    _, book = pending_bookings
    general = signin("general")
    ident = book(0)["reservationId"]
    approve(ctx, general, ident)
    mapping = ctx["db"].table("MSP_ADMIN_ROLE")
    with ctx["engine"].begin() as conn:
        conn.execute(delete(mapping).where(mapping.c.admin_id == "primary", mapping.c.role_code == PRIMARY))
    before = snapshot(ctx)
    result = ctx["client"].delete("/nadreego/admin/account", headers=general)
    assert result.status_code == 409 and result.json()["errorCode"] == "PRIMARY_ADMIN_REQUIRED_FOR_HANDOVER"
    assert snapshot(ctx) == before
    assert ctx["client"].get("/nadreego/shop/admin", headers=general).status_code == 200


def test_chat_revocation_failure_rolls_back_transfer_history_and_notification(privacy, pending_bookings, signin):
    from app.errors import Problem
    ctx = privacy
    _, book = pending_bookings
    general = signin("general")
    ident = book(0)["reservationId"]
    approve(ctx, general, ident)
    before = snapshot(ctx)
    ctx["chat"].revoke = lambda uid: (_ for _ in ()).throw(Problem(503, "CHAT_SYNC_FAILED"))
    result = ctx["client"].delete("/nadreego/admin/account", headers=general)
    assert result.status_code == 503
    assert snapshot(ctx) == before
    with ctx["engine"].connect() as conn:
        history = ctx["db"].table("MSP_RESERVATION_HISTORY")
        notification = ctx["db"].table("MSP_RENTAL_NOTIFICATION")
        assert conn.scalar(select(func.count()).select_from(history).where(history.c.event_type == "MANAGER_TRANSFERRED")) == 0
        assert conn.scalar(select(func.count()).select_from(notification).where(notification.c.event_type == "RESERVATION_MANAGER_TRANSFERRED")) == 0
    assert ctx["client"].get("/nadreego/shop/admin", headers=general).status_code == 200


@pytest.mark.parametrize("status", ["ON_RENT", "OVERDUE", "RETURNED"])
def test_primary_is_blocked_by_live_descendant_without_revoking_any_accounts(privacy, pending_bookings, signin, status):
    ctx = privacy
    _, book = pending_bookings
    primary = signin()
    ident = book(0)["reservationId"]
    approve(ctx, primary, ident)
    live_rental(ctx, ident)
    reservation, contract = ctx["db"].table("MSP_RESERVATION"), ctx["db"].table("MSP_RENTAL_CONTRACT")
    with ctx["engine"].begin() as conn:
        conn.execute(update(reservation).where(reservation.c.reservation_id == ident).values(spot_master_id="child"))
        conn.execute(update(contract).where(contract.c.reservation_id == ident).values(pickup_spot_master_id="child", contract_status=status))
    before = snapshot(ctx)
    result = ctx["client"].delete("/nadreego/admin/account", headers=primary)
    assert result.status_code == 409 and result.json()["errorCode"] == "DELETION_OBLIGATIONS_REMAIN"
    assert snapshot(ctx) == before
    assert ctx["client"].get("/nadreego/shop/admin", headers=primary).status_code == 200
