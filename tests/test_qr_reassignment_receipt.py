"""Deterministic QR detach/rebind interleavings in disposable SQLite only."""
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.security import sign_user_access
from test_customer_receipt import (BASE, at_period, count, external, new_quote, pending_bookings,
    prepare, receipt, receive, submit)
from test_external_reservations import approve, row


def replace_binding(ctx, session, source, target):
    """Inject another writer's observed result inside this isolated transaction.

    The API rolls this injection back on rejection; this is a deterministic
    race regression, not a claim of real MySQL concurrency verification.
    """
    table = ctx["tables"]["MSP_VEHICLE_QR"]
    previous = dict(session.execute(select(table).where(table.c.vehicle_id == source)).mappings().one())
    session.execute(delete(table).where(table.c.vehicle_id.in_({source, target})))
    session.execute(table.insert().values(**dict(previous, vehicle_id=target, qr_id=str(uuid4()))))


def test_qr_deleted_between_verification_reads_returns_not_found(receipt, monkeypatch):
    from app import rental_common

    ctx = receipt
    vehicle, raw = next(iter(ctx["qrs"].items()))
    original_rows, injected = rental_common.rows, []

    def detach_after_membership_read(session, table, *conditions):
        result = original_rows(session, table, *conditions)
        if table.name == "MSP_VEHICLE_SPOT_HISTORY" and not injected:
            injected.append(True)
            qr = ctx["tables"]["MSP_VEHICLE_QR"]
            session.execute(delete(qr).where(qr.c.vehicle_id == vehicle))
        return result

    monkeypatch.setattr("app.rental_common.rows", detach_after_membership_read)

    response = ctx["client"].post("/nadreego/vehicle/qr/validate", headers=ctx["admin"], json={"qrCode": raw})

    assert injected == [True]
    assert response.status_code == 404
    assert response.json()["errorCode"] == "QR_NOT_FOUND"
    assert count(ctx, "MSP_RESERVATION") == 0 and count(ctx, "MSP_RENTAL_CONTRACT") == 0


@pytest.mark.parametrize("replacement", ["OTHER_VEHICLE", "NEW_ISSUANCE_SAME_VEHICLE"])
def test_customer_resolution_rejects_binding_changed_after_initial_read(receipt, monkeypatch, replacement):
    from app import customer_qr

    ctx = receipt
    source, raw = next(iter(ctx["qrs"].items()))
    target = next(vehicle for vehicle in ctx["qrs"] if vehicle != source) if replacement == "OTHER_VEHICLE" else source
    verify, injected = customer_qr.verify_qr, []

    def rebind_before_verification(request, session, spot, original, *, lock=False):
        if not injected:
            injected.append(True)
            replace_binding(ctx, session, source, target)
        return verify(request, session, spot, original, lock=lock)

    monkeypatch.setattr("app.customer_qr.verify_qr", rebind_before_verification)

    response = ctx["client"].post(BASE + "/qr/lookup", headers=ctx["headers"], json={"qrCode": raw})

    assert injected == [True]
    assert response.status_code == 404
    assert response.json()["errorCode"] == "QR_NOT_FOUND"
    assert count(ctx, "MSP_RESERVATION") == 0 and count(ctx, "MSP_RENTAL_CONTRACT") == 0


def test_onsite_request_rechecks_quoted_vehicle_after_final_locked_resolution(receipt, monkeypatch):
    from app import customer_qr

    ctx = receipt
    source, raw = next(iter(ctx["qrs"].items()))
    target = next(vehicle for vehicle in ctx["qrs"] if vehicle != source)
    body, quote = new_quote(ctx, qr=raw)
    assert quote["vehicleId"] == source
    resolve, calls = customer_qr.resolve, []

    def rebind_before_locked_resolution(request, session, original, *, lock=False):
        calls.append(lock)
        if lock:
            replace_binding(ctx, session, source, target)
        return resolve(request, session, original, lock=lock)

    monkeypatch.setattr("app.customer_qr.resolve", rebind_before_locked_resolution)
    key = str(uuid4())

    response = submit(ctx, body, quote, key)

    assert calls == [False, True]
    assert response.status_code == 409
    assert response.json()["errorCode"] == "ONSITE_QUOTE_MISMATCH"
    assert response.json()["requestStatus"] == "REJECTED"
    assert count(ctx, "MSP_RESERVATION") == 0 and count(ctx, "MSP_RENTAL_CONTRACT") == 0
    assert count(ctx, "MSP_RESERVATION_HISTORY") == 0
    result = ctx["client"].get(BASE + "/onsite/requests/" + key, headers=ctx["headers"])
    assert result.status_code == 200
    assert result.json()["requestStatus"] == "REJECTED"
    assert result.json()["errorCode"] == "ONSITE_QUOTE_MISMATCH"


def test_completed_customer_receipt_replays_after_qr_is_reused_by_another_vehicle(receipt, monkeypatch):
    ctx = receipt
    ident = ctx["request_booking"](0)["reservationId"]
    approved = approve(ctx, ident)
    source = approved["assigned_vehicle_id"]
    raw = ctx["qrs"][source]
    target = next(vehicle for vehicle in ctx["qrs"] if vehicle != source)
    at_period(ctx, ident, monkeypatch)
    assert prepare(ctx, ident).status_code == 200
    received = receive(ctx, ident, qr=raw)
    assert received.status_code == 200, received.text
    contract = received.json()["item"]["rentalContractId"]
    returned = ctx["client"].post("/nadreego/vehicle/return", headers=ctx["admin"], json={"qrCode": raw})
    assert returned.status_code == 200, returned.text
    assert row(ctx, ident)["reservation_status"] == "RETURNED"
    rental = ctx["tables"]["MSP_RENTAL_VEHICLE"]
    with ctx["engine"].connect() as conn:
        plates = dict(conn.execute(select(rental.c.vehicle_id, rental.c.plate_number_full)).all())
    for vehicle in (source, target):
        detached = ctx["client"].post("/nadreego/sensor/delete", headers=ctx["admin"],
            json={"vehicleNumber": plates[vehicle], "division": "QR"})
        assert detached.status_code == 200, detached.text
    linked = ctx["client"].post("/nadreego/vehicle/qr/link", headers=ctx["admin"],
        json={"vehicleNumber": plates[target], "qrToken": raw})
    assert linked.status_code == 200, linked.text
    found = ctx["client"].post("/nadreego/vehicle/qr/validate", headers=ctx["admin"], json={"qrCode": raw})
    assert found.status_code == 200 and found.json()["data"]["vehicleId"] == target
    history_before, pushes_before = count(ctx, "MSP_RESERVATION_HISTORY"), len(ctx["fcm"].notifications)

    replay = receive(ctx, ident, qr=raw)

    assert replay.status_code == 200, replay.text
    assert replay.json()["item"]["rentalContractId"] == contract
    assert replay.json()["item"]["rentalStatus"] == "RETURNED"
    assert row(ctx, ident)["assigned_vehicle_id"] == source
    assert count(ctx, "MSP_RENTAL_CONTRACT") == 1
    assert count(ctx, "MSP_RESERVATION_HISTORY") == history_before
    assert len(ctx["fcm"].notifications) == pushes_before
    state = ctx["tables"]["MSP_VEHICLE_STATUS"]
    with ctx["engine"].connect() as conn:
        assert conn.scalar(select(state.c.status).where(state.c.vehicle_id == target)) == "AVAILABLE"
    other = {"Authorization": "Bearer " + sign_user_access(ctx["settings"], "pending-user-1")}
    assert receive(ctx, ident, qr=raw, headers=other).status_code == 404
