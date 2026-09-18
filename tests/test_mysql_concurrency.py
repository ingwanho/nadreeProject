from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app import auth, management
from app.security import PRIMARY

pytestmark = pytest.mark.mysql


def race(function, inputs):
    gate = Barrier(len(inputs))

    def call(value):
        gate.wait(timeout=10)
        return function(value)

    with ThreadPoolExecutor(max_workers=len(inputs)) as workers:
        return list(workers.map(call, inputs))


def test_mysql_refresh_can_be_consumed_only_once(client, signin):
    headers = signin()
    results = race(lambda _: client.get("/nadreego/admin/refresh", headers=headers), [0, 1])
    assert sorted(result.status_code for result in results) == [200, 401]


def test_mysql_role_transfer_rechecks_role_after_waiting_for_spot_lock(client, signin, setup, monkeypatch):
    headers = signin()
    gate = Barrier(2)
    original = management.principal

    def synchronized_principal(request, session):
        actor = original(request, session)
        gate.wait(timeout=10)
        return actor

    monkeypatch.setattr(management, "principal", synchronized_principal)
    results = race(lambda target: client.post("/nadreego/admin/roleChange", headers=headers, json={"adminId": target}),
                   ["general", "general2"])
    assert sorted(result.status_code for result in results) == [200, 403]
    admins, mapping = setup["db"].table("MSP_ADMIN"), setup["db"].table("MSP_ADMIN_ROLE")
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(func.count()).select_from(admins.join(mapping, admins.c.admin_id == mapping.c.admin_id))
            .where(admins.c.primary_spot_master_id == "root", mapping.c.role_code == PRIMARY)) == 1


def test_mysql_child_code_allocation_is_serialized(client, signin):
    headers = signin()
    results = race(lambda name: client.post("/api/v1/organizations/spots", headers=headers,
        json={"spot_name": name, "unit_type": "spot", "parent_spot_id": "root"}), ["One", "Two"])
    assert [result.status_code for result in results] == [200, 200]
    assert len({result.json()["unit_code"] for result in results}) == 2


def test_mysql_email_change_serializes_new_email_claim(client, signin, monkeypatch):
    headers = [signin("general"), signin("general2")]
    gate = Barrier(2)
    original = auth.lock_email

    def synchronized_lock(session, email):
        gate.wait(timeout=10)
        original(session, email)

    monkeypatch.setattr(auth, "lock_email", synchronized_lock)
    results = race(lambda header: client.post("/nadreego/admin/update", headers=header,
        json={"email": "same-new@example.com"}), headers)
    assert sorted(result.status_code for result in results) == [200, 409]


def test_mysql_request_approval_and_rejection_only_process_once(client, signin, applicant, setup):
    email, headers = applicant(), signin()
    results = race(lambda action: client.post("/nadreego/shop/adminRequestAction", headers=headers,
        json={"email": email, "action": action}), ["APPROVE", "REJECT"])
    assert sorted(result.status_code for result in results) == [200, 409]
    table = setup["db"].table("MSP_RENTAL_ADMIN_REQUEST")
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(table.c.status).where(table.c.email == email)) in ["APPROVED", "REJECTED"]


def test_mysql_same_account_cannot_join_two_spots(client, signin, applicant, setup):
    email = applicant()
    pending = setup["db"].table("MSP_RENTAL_ADMIN_REQUEST")
    with setup["engine"].begin() as conn:
        conn.execute(pending.insert().values(request_id="foreign-request", admin_id="applicant",
            email=email, spot_master_id="foreign"))
    headers = [signin(), signin("outsider")]
    results = race(lambda header: client.post("/nadreego/shop/adminRequestAction", headers=header,
        json={"email": email, "action": "APPROVE"}), headers)
    assert sorted(result.status_code for result in results) == [200, 409]
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(func.count()).select_from(pending).where(pending.c.status == "APPROVED")) == 1
