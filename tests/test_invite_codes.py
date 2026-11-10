"""Short branch invitations remain unique, atomic, and single-use."""
import re
import string

from sqlalchemy import select

from app.rental_common import lock_key
from app.security import PRIMARY
from test_management import rental_tables


CREATE = "/api/v1/organizations/spots"


def create_body(name):
    return {"spot_name": name, "unit_type": "spot", "parent_spot_id": "root",
        "email": "isolated-shop@example.com", "address": "Isolated branch entrance",
        "lat": -8.65, "lng": 115.2}


def rows(setup, name):
    with setup["engine"].connect() as connection:
        return [dict(row) for row in connection.execute(select(setup["db"].table(name))).mappings()]


def occupy_code(setup, code):
    table = setup["db"].table("MSP_SPOT_RENT")
    with setup["engine"].begin() as connection:
        connection.execute(table.update().where(table.c.spot_master_id == "root").values(invite_code=code))


def deterministic_codes(monkeypatch, candidates):
    characters = iter("".join(candidates))
    choices, locks = [], []

    def choose(alphabet):
        assert alphabet == string.ascii_uppercase + string.digits
        choices.append(alphabet)
        return next(characters)

    def record_lock(session, namespace, value):
        locks.append((namespace, value))
        return lock_key(session, namespace, value)

    monkeypatch.setattr("app.management.secrets.choice", choose)
    monkeypatch.setattr("app.management.lock_key", record_lock)
    return choices, locks


def test_invite_code_collision_retries_without_changing_existing_owner(client, signin, setup, monkeypatch):
    headers = signin()
    occupy_code(setup, "AAAAAAAA")
    previous = rows(setup, "MSP_SPOT_RENT")
    choices, locks = deterministic_codes(monkeypatch, ["AAAAAAAA", "BBBBBBBB"])

    response = client.post(CREATE, headers=headers, json=create_body("Collision retry branch"))

    assert response.status_code == 200, response.text
    created = response.json()
    assert created["inviteCode"] == "BBBBBBBB"
    assert len(choices) == 16
    assert locks == [("invite-code", "AAAAAAAA"), ("invite-code", "BBBBBBBB")]
    current = rows(setup, "MSP_SPOT_RENT")
    assert [row for row in current if row["spot_master_id"] != created["spot_id"]] == previous
    assert next(row for row in current if row["spot_master_id"] == created["spot_id"])["invite_code"] == "BBBBBBBB"


def test_ten_invite_collisions_roll_back_master_normalized_and_rental_rows(client, signin, setup, monkeypatch):
    headers = signin()
    occupy_code(setup, "AAAAAAAA")
    names = ("MSP_SPOT_MASTER", "MSP_REGION", "MSP_LOCAL", "MSP_SPOT", "MSP_SPOT_RENT")
    before = {name: rows(setup, name) for name in names}
    choices, locks = deterministic_codes(monkeypatch, ["AAAAAAAA"] * 10)

    response = client.post(CREATE, headers=headers, json=create_body("Exhausted collision branch"))

    assert response.status_code == 503, response.text
    assert response.json()["errorCode"] == "INVITE_CODE_GENERATION_FAILED"
    assert len(choices) == 80
    assert locks == [("invite-code", "AAAAAAAA")] * 10
    assert {name: rows(setup, name) for name in names} == before


def test_public_eight_character_invite_activates_one_representative_and_is_consumed(client, signin, setup):
    existing_invites = rows(setup, "MSP_SPOT_RENT")
    response = client.post(CREATE, headers=signin(), json=create_body("Short invite signup branch"))
    assert response.status_code == 200, response.text
    created = response.json()
    assert re.fullmatch(r"[A-Z0-9]{8}", created["inviteCode"])
    assert [row for row in rows(setup, "MSP_SPOT_RENT") if row["spot_master_id"] != created["spot_id"]] == existing_invites

    signup = client.post("/nadreego/admin/signup", json={
        "loginId": "short-invite-manager", "email": "short-invite-manager@example.com",
        "password": "Test-password-123!", "name": "Isolated representative", "inviteCode": created["inviteCode"]})

    assert signup.status_code == 201, signup.text
    accepted = signup.json()
    assert accepted["accountStatus"] == "ACTIVE" and accepted["spotMasterId"] == created["spot_id"]
    assert accepted["requestId"] is None and accepted["requestStatus"] is None
    with setup["engine"].connect() as connection:
        rent = setup["db"].table("MSP_SPOT_RENT")
        mapping = setup["db"].table("MSP_ADMIN_ROLE")
        assert connection.scalar(select(rent.c.invite_code).where(rent.c.spot_master_id == created["spot_id"])) is None
        assert connection.scalar(select(mapping.c.role_code).where(mapping.c.admin_id == accepted["adminId"])) == PRIMARY
    admins = rows(setup, "MSP_ADMIN")

    reused = client.post("/nadreego/admin/signup", json={
        "loginId": "short-invite-reuse", "email": "short-invite-reuse@example.com",
        "password": "Test-password-123!", "name": "Rejected second representative", "inviteCode": created["inviteCode"]})

    assert reused.status_code == 404 and reused.json()["errorCode"] == "INVITE_CODE_NOT_FOUND"
    assert rows(setup, "MSP_ADMIN") == admins
