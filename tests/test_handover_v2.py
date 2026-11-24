"""State/permission/transaction regressions; disposable SQL and a storage double."""
import uuid

from cryptography.fernet import Fernet
from pydantic import SecretStr
import pytest
from sqlalchemy import func, select

from app.errors import Problem
from test_external_reservations import external, during_period, row
from test_pending_reservation_approval import pending_bookings

BASE = "/api/v1/nadree/rental"


class MediaDouble:
    ttl = 900

    def __init__(self):
        self.available = set()

    def prepare(self, key, content_type, size):
        return {"url": "https://example.invalid/upload", "fields": {"key": key}}

    def finalize(self, slot, key):
        if slot["uploadId"] not in self.available:
            raise Problem(409, "MEDIA_UPLOAD_NOT_FOUND")
        return {"key": key, "durationSeconds": 9.5 if slot["contentType"] == "video/mp4" else None, "sha256": "test-checksum"}

    def url(self, key):
        return "https://example.invalid/private-media"

    def close(self):
        pass


@pytest.fixture
def handover(external, monkeypatch):
    ctx = external
    ctx["settings"].field_encrypt_key = SecretStr(Fernet.generate_key().decode())
    ctx["app"].state.handover_media = MediaDouble()
    rid = ctx["request_booking"](0, legacy=False)["reservationId"]
    response = ctx["client"].post("/nadreego/booking/action", headers=ctx["admin"], json={
        "bookedNo": "BO" + rid, "action": "APPROVE", "finalPrice": 25})
    assert response.status_code == 200, response.text
    hid = response.json()["data"]["handoverId"]
    at = during_period(ctx, rid, monkeypatch)
    monkeypatch.setattr("app.handover.now", lambda: at)
    ctx.update(rid=rid, hid=hid)
    return ctx


def command(ctx, suffix, body=None, *, admin=False, headers=None):
    prefix = "/nadreego/handovers/" if admin else BASE + "/handovers/"
    return ctx["client"].post(prefix + ctx["hid"] + suffix,
        headers=headers or ctx["admin" if admin else "headers"], json=body if body is not None else {})


def begin(ctx):
    response = ctx["client"].post(BASE + "/reservations/" + ctx["rid"] + "/handover", headers=ctx["headers"],
        json={"clientRequestId": str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    return response


def form(ctx, **fields):
    return ctx["client"].patch(BASE + "/handovers/" + ctx["hid"] + "/form", headers=ctx["headers"], json=fields)


def submit_form(ctx):
    response = form(ctx, passportNumber="TEST-PASSPORT", accommodationLocation="Test hotel", helmetCount=0)
    assert response.status_code == 200, response.text
    response = command(ctx, "/submit")
    assert response.status_code == 200, response.text


def video(ctx):
    response = command(ctx, "/media/uploads", {"clientFileId": str(uuid.uuid4()), "kind": "VEHICLE_VIDEO",
                                             "contentType": "video/mp4", "sizeBytes": 1000})
    assert response.status_code == 200, response.text
    upload = response.json()["upload"]["uploadId"]
    ctx["app"].state.handover_media.available.add(upload)
    response = command(ctx, "/media/uploads/" + upload + "/complete")
    assert response.status_code == 200, response.text
    return upload


def claim(ctx, headers=None, *, extra=True):
    response = command(ctx, "/claim", {"trigger": "REVIEW_WITHOUT_PHOTOS"}, admin=True, headers=headers)
    assert response.status_code == 200, response.text
    if extra:
        extra_photo(ctx, headers=headers)
    return response


def extra_photo(ctx, headers=None):
    response = command(ctx, "/media/uploads", {"clientFileId": str(uuid.uuid4()), "kind": "EXTRA_PHOTO",
        "contentType": "image/jpeg", "sizeBytes": 1000}, admin=True, headers=headers)
    assert response.status_code == 200, response.text
    upload = response.json()["upload"]["uploadId"]
    ctx["app"].state.handover_media.available.add(upload)
    result = command(ctx, "/media/uploads/" + upload + "/complete", admin=True, headers=headers)
    assert result.status_code == 200, result.text
    return result


def test_extra_photo_is_required_and_cannot_be_skipped(handover):
    ctx = handover
    begin(ctx)
    claim(ctx, extra=False)
    submit_form(ctx)
    video(ctx)
    assert command(ctx, "/signature/complete").status_code == 200
    missing = command(ctx, "/review", {"action": "CONFIRM"}, admin=True)
    assert missing.status_code == 409 and missing.json()["errorCode"] == "MEDIA_NOT_READY"
    skipped = command(ctx, "/review", {"action": "CONFIRM", "skipPhotoKinds": ["EXTRA_PHOTO"]}, admin=True)
    assert skipped.status_code == 422
    assert start_rent(ctx).json()["errorCode"] == "HANDOVER_NOT_READY"
    uploaded = extra_photo(ctx)
    assert uploaded.json()["item"]["media"]["extraPhoto"]["required"] is True
    assert command(ctx, "/review", {"action": "CONFIRM", "skipPhotoKinds": ["PASSPORT_PHOTO", "DRIVER_LICENSE_PHOTO"]}, admin=True).status_code == 200
    assert start_rent(ctx).status_code == 200


def start_rent(ctx):
    return ctx["client"].post("/nadreego/rent/approve", headers=ctx["admin"], json={
        "bookedNo": "BO" + ctx["rid"], "handoverId": ctx["hid"], "receiptRequired": True,
        "qrCode": ctx["qrs"][row(ctx, ctx["rid"])["assigned_vehicle_id"]]})


def test_approval_creates_one_priced_preparation_and_requires_manual_price(external):
    ctx = external
    rid = ctx["request_booking"](0, legacy=False)["reservationId"]
    body = {"bookedNo": "BO" + rid, "action": "APPROVE"}
    assert ctx["client"].post("/nadreego/booking/action", headers=ctx["admin"], json=body).status_code == 422
    assert row(ctx, rid)["reservation_status"] == "REQUESTED"
    body.update(finalPrice=25)
    removed_field = ctx["client"].post("/nadreego/booking/action", headers=ctx["admin"], json={**body, "currency": "USD"})
    assert removed_field.status_code == 422
    first = ctx["client"].post("/nadreego/booking/action", headers=ctx["admin"], json=body)
    second = ctx["client"].post("/nadreego/booking/action", headers=ctx["admin"], json=body)
    assert first.status_code == second.status_code == 200, first.text
    assert first.json()["data"]["handoverId"] == second.json()["data"]["handoverId"]
    assert first.json()["data"]["handoverStatus"] == "NOT_STARTED"
    body["finalPrice"] = 26
    assert ctx["client"].post("/nadreego/booking/action", headers=ctx["admin"], json=body).json()["errorCode"] == "FINAL_PRICE_ALREADY_CONFIRMED"
    h = ctx["db"].table("MSP_RENTAL_HANDOVER")
    with ctx["engine"].connect() as connection:
        assert connection.scalar(select(func.count()).select_from(h)) == 1


@pytest.mark.parametrize("admin_first", [True, False])
def test_independent_completion_and_single_rental(handover, admin_first):
    ctx = handover
    begin(ctx)
    claim(ctx)
    assert command(ctx, "/review", {"action": "CONFIRM"}, admin=True).json()["errorCode"] == "CUSTOMER_FORM_NOT_SUBMITTED"
    assert command(ctx, "/signature/complete").json()["errorCode"] == "CUSTOMER_FORM_NOT_SUBMITTED"
    assert command(ctx, "/submit").status_code == 422
    submit_form(ctx)
    assert command(ctx, "/signature/complete").json()["errorCode"] == "VIDEO_NOT_READY"
    if admin_first:
        response = command(ctx, "/review", {"action": "CONFIRM"}, admin=True)
        assert response.status_code == 200, response.text
        assert response.json()["item"]["customerStatus"] == "SUBMITTED"
        assert response.json()["item"]["canStartRental"] is False
    video(ctx)
    signed = command(ctx, "/signature/complete")
    assert signed.status_code == 200, signed.text
    if not admin_first:
        assert signed.json()["item"]["handoverStatus"] == "IN_PROGRESS"
        assert command(ctx, "/review", {"action": "CONFIRM"}, admin=True).status_code == 200
    assert command(ctx, "/signature/complete").status_code == 200
    result = start_rent(ctx)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["finalPrice"] == 25
    repeated = start_rent(ctx)
    assert repeated.status_code == 200, repeated.text
    assert result.json()["data"]["rentalContractId"] == repeated.json()["data"]["rentalContractId"]
    detail = ctx["client"].get(BASE + "/reservations/" + ctx["rid"], headers=ctx["headers"])
    assert detail.status_code == 200, detail.text
    data = detail.json()["item"]
    assert data["bookedNo"] == "BO" + ctx["rid"] and data["recordType"] == "RENTAL"
    assert data["form"]["helmetCount"] == 0 and data["form"]["passportNumber"] == "TEST-PASSPORT"
    assert data["price"]["finalTotal"] == data["finalPrice"] == 25


def test_form_synchronizes_only_supplied_profile_fields_and_encrypts(handover):
    ctx = handover
    begin(ctx)
    response = form(ctx, passportNumber="TEST-NEW-PASSPORT", driverLicenseNumber="TEST-LICENSE",
                    snsInfo={"instagram": "test_new"})
    assert response.status_code == 200, response.text
    profile = ctx["client"].get("/api/v1/nadree/user/profile", headers=ctx["headers"]).json()["user"]
    assert profile["passportNumber"] == "TEST-NEW-PASSPORT"
    assert profile["driverLicenseNumber"] == "TEST-LICENSE"
    assert profile["snsInfo"] == {"instagram": "test_new"}
    assert form(ctx, helmetCount=0).status_code == 200
    profile_after = ctx["client"].get("/api/v1/nadree/user/profile", headers=ctx["headers"]).json()["user"]
    assert profile_after == profile
    users = ctx["db"].table("MSP_RENTAL_USER")
    with ctx["engine"].connect() as connection:
        stored = connection.execute(select(users).where(users.c.uid_token == "pending-user-0")).mappings().one()
        assert stored["passport_number_enc"] != profile["passportNumber"]
        assert stored["driver_license_number_enc"] != profile["driverLicenseNumber"]
    assert form(ctx, uidToken="pending-user-1", passportNumber="OTHER").status_code == 422


def test_one_claim_and_submitted_form_visibility(handover, signin):
    ctx = handover
    begin(ctx)
    claim(ctx)
    second = command(ctx, "/claim", {"trigger": "PHOTO_CAPTURE_STARTED"}, admin=True, headers=signin("general"))
    assert second.json()["errorCode"] == "HANDOVER_ALREADY_ASSIGNED"
    path = "/nadreego/handovers/" + ctx["hid"]
    assert ctx["client"].get(path, headers=ctx["admin"]).json()["item"]["form"] is None
    assert ctx["client"].get(path, headers=signin("outsider")).status_code == 404
    submit_form(ctx)
    assert ctx["client"].get(path, headers=ctx["admin"]).json()["item"]["form"]["passportNumber"] == "TEST-PASSPORT"


def test_assigned_handover_transfers_even_when_approved_by_primary(handover, signin):
    ctx = handover
    begin(ctx)
    general = signin("general")
    claim(ctx, headers=general)
    from app.admin_rental_exit import transfer_approved_work
    from sqlalchemy.orm import Session
    with Session(ctx["engine"]) as session, session.begin():
        assert transfer_approved_work(ctx["db"], session, "root", "general") == 1
    h = ctx["db"].table("MSP_RENTAL_HANDOVER")
    with ctx["engine"].connect() as conn:
        assert conn.scalar(select(h.c.assigned_admin_id).where(h.c.handover_id == ctx["hid"])) == "primary"
    assert command(ctx, "/claim", {"trigger": "PHOTO_CAPTURE_STARTED"}, admin=True, headers=general).json()["errorCode"] == "HANDOVER_ALREADY_ASSIGNED"


def test_video_upload_order_and_invalid_form_updates_do_not_change_profile(handover):
    ctx = handover
    begin(ctx)
    assert command(ctx, "/media/uploads", {"clientFileId": str(uuid.uuid4()), "kind": "VEHICLE_VIDEO",
        "contentType": "video/mp4", "sizeBytes": 4}).json()["errorCode"] == "CUSTOMER_FORM_NOT_SUBMITTED"
    for fields in ({"helmetCount": False}, {"helmetCount": -1}, {"passportNumber": " "},
                   {"passportNumber": "VALID", "helmetCount": None}):
        assert form(ctx, **fields).status_code == 422
    profile = ctx["client"].get("/api/v1/nadree/user/profile", headers=ctx["headers"]).json()["user"]
    assert profile["passportNumber"] is None
    assert form(ctx, passportNumber="TEST", accommodationLocation="Test hotel").status_code == 200
    assert command(ctx, "/submit").status_code == 422
    assert form(ctx, helmetCount=0).status_code == 200
    assert command(ctx, "/submit").status_code == 200


def test_prepared_form_previews_owner_profile_without_copying_it_early(handover):
    ctx = handover
    profile = ctx["client"].patch("/api/v1/nadree/user/profile", headers=ctx["headers"],
        json={"passportNumber": "PROFILE-BEFORE-START"})
    assert profile.status_code == 200, profile.text
    detail = ctx["client"].get(BASE + "/reservations/" + ctx["rid"], headers=ctx["headers"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["item"]["form"]["passportNumber"] == "PROFILE-BEFORE-START"
    admin = ctx["client"].get("/nadreego/handovers/" + ctx["hid"], headers=ctx["admin"])
    assert admin.json()["item"]["form"] is None
    h = ctx["db"].table("MSP_RENTAL_HANDOVER")
    with ctx["engine"].connect() as conn:
        assert conn.scalar(select(h.c.passport_number_enc).where(h.c.handover_id == ctx["hid"])) is None
    begin(ctx)
    assert ctx["client"].patch("/api/v1/nadree/user/profile", headers=ctx["headers"],
        json={"passportNumber": "PROFILE-LATER"}).status_code == 200
    detail = ctx["client"].get(BASE + "/handovers/" + ctx["hid"], headers=ctx["headers"])
    assert detail.json()["item"]["form"]["passportNumber"] == "PROFILE-BEFORE-START"


@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT"])
def test_single_change_proposal_and_customer_decision(handover, decision):
    ctx = handover
    begin(ctx)
    claim(ctx)
    submit_form(ctx)
    proposal = {"action": "PROPOSE_CHANGES", "changes": {"passportNumber": "TEST-CORRECTED"}, "reason": "Please confirm."}
    assert command(ctx, "/review", proposal, admin=True).status_code == 200
    profile = lambda: ctx["client"].get("/api/v1/nadree/user/profile", headers=ctx["headers"]).json()["user"]
    assert profile()["passportNumber"] == "TEST-PASSPORT"
    result = command(ctx, "/changes/respond", {"decision": decision})
    assert result.status_code == 200, result.text
    assert profile()["passportNumber"] == ("TEST-CORRECTED" if decision == "ACCEPT" else "TEST-PASSPORT")
    if decision == "REJECT":
        assert row(ctx, ctx["rid"])["reservation_status"] == "APPROVED"
        assert result.json()["item"]["handoverStatus"] == "CANCELED"
        new_id = result.json()["item"]["restartHandoverId"]
        assert new_id and new_id != ctx["hid"]
        restart = ctx["client"].post(BASE + "/reservations/" + ctx["rid"] + "/handover", headers=ctx["headers"],
            json={"clientRequestId": str(uuid.uuid4())})
        assert restart.status_code == 200, restart.text
        assert restart.json()["item"]["handoverId"] == new_id
        assert restart.json()["item"]["customerStatus"] == "DRAFT"
        assert restart.json()["item"]["finalPrice"] == 25
        assert restart.json()["item"]["assignedAdminId"] is None
        h = ctx["db"].table("MSP_RENTAL_HANDOVER")
        with ctx["engine"].connect() as conn:
            assert conn.scalar(select(func.count()).select_from(h).where(h.c.handover_status != "CANCELED")) == 1
            assert conn.scalar(select(func.count()).select_from(ctx["db"].table("MSP_RENTAL_PAYMENT"))) == 0
    else:
        assert result.json()["item"]["customerStatus"] == "SUBMITTED"
        changed = ctx["client"].patch("/api/v1/nadree/user/profile", headers=ctx["headers"], json={"passportNumber": "TEST-LATER"})
        assert changed.status_code == 200, changed.text
    assert command(ctx, "/changes/respond", {"decision": decision}).status_code == 200
    if decision == "ACCEPT":
        assert profile()["passportNumber"] == "TEST-LATER"
