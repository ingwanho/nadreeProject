from datetime import timedelta

import pytest
from sqlalchemy import delete, select, update

from app.errors import Problem
from app.security import GENERAL, PRIMARY, now
from test_pending_reservation_approval import pending_bookings


PATH = "/nadreego/admin/account"


@pytest.fixture(autouse=True)
def rental_tables(setup):
    from app.rental_schema import metadata
    metadata.create_all(setup["engine"])


def snapshot(setup):
    with setup["engine"].connect() as conn:
        return {name: conn.execute(select(setup["db"].table(name))).mappings().all()
                for name in ("MSP_ADMIN", "MSP_ADMIN_ROLE", "MSP_REFRESH_TOKEN", "MSP_ADMIN_SPOT_SCOPE",
                             "MSP_SPOT_MASTER", "MSP_SPOT_RENT", "MSP_ORG", "MSP_REGION", "MSP_LOCAL", "MSP_SPOT")}


def assert_removed(client, admin_id, headers):
    assert client.get("/nadreego/shop/admin", headers=headers).status_code == 401
    assert client.get("/nadreego/admin/refresh", headers=headers).status_code == 401
    login = client.post("/nadreego/admin/login", json={
        "email": admin_id + "@example.com", "password": "Test-password-123!"})
    assert login.status_code == 403 and login.json()["errorCode"] == "RENTAL_ROLE_REQUIRED"


def test_general_deletes_only_self_and_preserves_shared_account(client, signin, setup, monkeypatch):
    own, primary, colleague = signin("general", fcmToken="own-device"), signin(), signin("general2")
    mapping, tokens = setup["db"].table("MSP_ADMIN_ROLE"), setup["db"].table("MSP_REFRESH_TOKEN")
    with setup["engine"].begin() as conn:
        conn.execute(mapping.insert().values(admin_id="general", role_code="viewer", assigned_at=now()))
        conn.execute(tokens.insert().values(token_id="other-service", admin_id="general", token_hash="other-service",
            user_agent="other-service", issued_at=now(), expires_at=now() + timedelta(days=1)))
    before = snapshot(setup)
    revoked = []
    monkeypatch.setattr("app.chat.revoke_admin_chat", lambda request, admin_id: revoked.append(admin_id))
    response = client.delete(PATH, headers=own)
    assert response.status_code == 200
    assert response.json() == {"status": "success", "deleted": True, "scope": "SELF",
                               "spotMasterId": "root", "deletedAdminCount": 1, "deletedSpotCount": 0}
    after = snapshot(setup)
    assert revoked == ["general"]
    account = next(row for row in after["MSP_ADMIN"] if row["admin_id"] == "general")
    assert account["is_active"] == 1 and account["fcm_token"] is None
    assert {row["role_code"] for row in after["MSP_ADMIN_ROLE"] if row["admin_id"] == "general"} == {"viewer"}
    assert next(row for row in after["MSP_REFRESH_TOKEN"] if row["token_id"] == "other-service")["revoked_at"] is None
    assert before["MSP_ADMIN_SPOT_SCOPE"] == after["MSP_ADMIN_SPOT_SCOPE"]
    assert before["MSP_SPOT_MASTER"] == after["MSP_SPOT_MASTER"]
    assert_removed(client, "general", own)
    assert client.get("/nadreego/shop/admin", headers=primary).status_code == 200
    assert client.get("/nadreego/shop/admin", headers=colleague).status_code == 200
    assert client.delete(PATH, headers=own).status_code == 401


@pytest.mark.parametrize("legacy_spot_key", [True, False])
def test_primary_deletes_self_subtree_admins_and_spots(client, signin, setup, applicant, monkeypatch, legacy_spot_key):
    primary, general, general2, outsider = signin(), signin("general"), signin("general2"), signin("outsider")
    applicant("child-admin", "child", primary_spot_master_id="child", contract_id="CT1")
    applicant("web-only")
    mapping = setup["db"].table("MSP_ADMIN_ROLE")
    scope = setup["db"].table("MSP_ADMIN_SPOT_SCOPE")
    with setup["engine"].begin() as conn:
        if not legacy_spot_key:
            master = setup["db"].table("MSP_SPOT_MASTER")
            conn.execute(update(master).where(master.c.spot_master_id == "child").values(spot_id=None))
        conn.execute(mapping.insert(), [
            {"admin_id": "child-admin", "role_code": PRIMARY},
            {"admin_id": "web-only", "role_code": "viewer"},
            {"admin_id": "primary", "role_code": "viewer"}])
        conn.execute(scope.insert().values(admin_id="child-admin", spot_master_id="child", access_type="manage"))
    child = signin("child-admin")
    before = snapshot(setup)
    revoked = []
    monkeypatch.setattr("app.chat.revoke_admin_chat", lambda request, admin_id: revoked.append(admin_id))
    response = client.delete(PATH, headers=primary)
    assert response.status_code == 200
    assert response.json() == {"status": "success", "deleted": True, "scope": "SUBTREE",
                               "spotMasterId": "root", "deletedAdminCount": 4, "deletedSpotCount": 2}
    assert set(revoked) == {"primary", "general", "general2", "child-admin"}
    after = snapshot(setup)
    assert len(before["MSP_ADMIN"]) == len(after["MSP_ADMIN"])
    assert before["MSP_ADMIN_SPOT_SCOPE"] == after["MSP_ADMIN_SPOT_SCOPE"]
    assert {(row["admin_id"], row["role_code"]) for row in after["MSP_ADMIN_ROLE"]} == {
        ("primary", "viewer"), ("web-only", "viewer"), ("outsider", PRIMARY)}
    assert {row["spot_master_id"]: row["is_active"] for row in after["MSP_SPOT_MASTER"]} == {
        "root": 0, "child": 0, "sibling": 1, "foreign": 1}
    assert next(row for row in after["MSP_ORG"] if row["org_id"] == "root")["is_active"] == 0
    assert next(row for row in after["MSP_SPOT"] if row["spot_id"] == "child")["is_active"] == 0
    assert before["MSP_SPOT_RENT"] == after["MSP_SPOT_RENT"]
    for admin_id, headers in (("primary", primary), ("general", general), ("general2", general2), ("child-admin", child)):
        assert_removed(client, admin_id, headers)
    assert client.get("/nadreego/shop/admin", headers=outsider).status_code == 200


def test_primary_also_removes_inactive_and_expired_members(client, signin, setup):
    primary = signin()
    admins, mapping = setup["db"].table("MSP_ADMIN"), setup["db"].table("MSP_ADMIN_ROLE")
    with setup["engine"].begin() as conn:
        conn.execute(update(admins).where(admins.c.admin_id == "general2").values(is_active=0))
        conn.execute(update(mapping).where(mapping.c.admin_id == "general2").values(expires_at=now() - timedelta(days=1)))
    response = client.delete(PATH, headers=primary)
    assert response.status_code == 200 and response.json()["deletedAdminCount"] == 3
    with setup["engine"].connect() as conn:
        assert not conn.execute(select(mapping).where(mapping.c.admin_id == "general2")).first()


def test_branch_primary_deletes_all_depths_but_preserves_parent_and_sibling(client, signin, setup, applicant):
    company = signin()
    parent = "root"
    created = []
    for level in ("region", "local", "spot"):
        response = client.post("/api/v1/organizations/spots", headers=company, json={
            "spot_name": "Delete test " + level, "unit_type": level, "parent_spot_id": parent,
            "email": "shop@example.com", "address": "Test address", "lat": -8.6, "lng": 115.2})
        assert response.status_code == 200, response.text
        created.append(response.json()["spot_id"])
        parent = created[-1]
    mapping, scope = setup["db"].table("MSP_ADMIN_ROLE"), setup["db"].table("MSP_ADMIN_SPOT_SCOPE")
    for ident, spot, role in (("branch-primary", created[0], PRIMARY), ("leaf-general", created[-1], GENERAL)):
        applicant(ident, spot, primary_spot_master_id=spot, contract_id="CT1")
        with setup["engine"].begin() as conn:
            conn.execute(mapping.insert().values(admin_id=ident, role_code=role))
            conn.execute(scope.insert().values(admin_id=ident, spot_master_id=spot, access_type="manage"))
    branch = signin("branch-primary")
    response = client.delete(PATH, headers=branch)
    assert response.status_code == 200
    assert response.json() == {"status": "success", "deleted": True, "scope": "SUBTREE",
        "spotMasterId": created[0], "deletedAdminCount": 2, "deletedSpotCount": 3}
    master = setup["db"].table("MSP_SPOT_MASTER")
    with setup["engine"].connect() as conn:
        states = dict(conn.execute(select(master.c.spot_master_id, master.c.is_active)).all())
        assert all(states[spot] == 0 for spot in created)
        assert all(states[spot] == 1 for spot in ("root", "child", "sibling", "foreign"))
        for level, ident in zip(("region", "local", "spot"), created):
            normal = setup["db"].table("MSP_" + level.upper())
            assert conn.scalar(select(normal.c.is_active).where(normal.c[level + "_id"] == ident)) == 0
        org = setup["db"].table("MSP_ORG")
        assert conn.scalar(select(org.c.is_active).where(org.c.org_id == "root")) == 1
    assert client.get("/nadreego/shop/admin", headers=company).status_code == 200
    rejected = client.post("/api/v1/organizations/spots", headers=company, json={
        "spot_name": "Under deleted branch", "unit_type": "local", "parent_spot_id": created[0]})
    assert rejected.status_code == 404 and rejected.json()["errorCode"] == "PARENT_SPOT_NOT_FOUND"


def test_subtree_requires_same_company_contract_and_segment_boundary(client, signin, setup):
    headers = signin()
    master = setup["db"].table("MSP_SPOT_MASTER")
    with setup["engine"].begin() as conn:
        conn.execute(update(master).where(master.c.spot_master_id == "sibling").values(org_id="root"))
        conn.execute(update(master).where(master.c.spot_master_id == "foreign").values(
            org_id="root", unit_code="CT1-ORG01-SP99"))
    response = client.delete(PATH, headers=headers)
    assert response.status_code == 200 and response.json()["deletedSpotCount"] == 2
    with setup["engine"].connect() as conn:
        assert dict(conn.execute(select(master.c.spot_master_id, master.c.is_active)).all()) == {
            "root": 0, "child": 0, "sibling": 1, "foreign": 1}


def test_primary_cannot_close_spots_with_unfinished_bookings(client, signin, setup, pending_bookings):
    _, request_booking = pending_bookings
    existing = request_booking(0)["reservationId"]
    names = ("MSP_RESERVATION", "MSP_RESERVATION_HISTORY", "MSP_RENTAL_CONTRACT", "MSP_RENTAL_PAYMENT",
             "MSP_VEHICLE", "MSP_VEHICLE_STATUS", "MSP_VEHICLE_QR", "MSP_VEHICLE_SPOT_HISTORY")
    with setup["engine"].connect() as conn:
        before = {name: conn.execute(select(setup["db"].table(name))).mappings().all() for name in names}
    headers = signin()
    response = client.delete(PATH, headers=headers)
    assert response.status_code == 409 and response.json()["errorCode"] == "DELETION_OBLIGATIONS_REMAIN"
    with setup["engine"].connect() as conn:
        assert {name: conn.execute(select(setup["db"].table(name))).mappings().all() for name in names} == before
    assert request_booking(1)["reservationStatus"] == "REQUESTED"
    from app.security import sign_user_access
    own = {"Authorization": "Bearer " + sign_user_access(setup["settings"], "pending-user-0")}
    assert client.get("/api/v1/nadree/rental/reservations/" + existing, headers=own).status_code == 200
    assert client.get("/nadreego/shop/admin", headers=headers).status_code == 200


def test_late_database_failure_rolls_back_members_and_all_spot_tables(client, signin, setup):
    from sqlalchemy import event
    from sqlalchemy.exc import IntegrityError
    headers = signin()
    before = snapshot(setup)

    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith('UPDATE "MSP_SPOT" '):
            raise IntegrityError(statement, None, Exception("isolated failure"))

    event.listen(setup["engine"], "before_cursor_execute", fail)
    try:
        response = client.delete(PATH, headers=headers)
    finally:
        event.remove(setup["engine"], "before_cursor_execute", fail)
    assert response.status_code == 409 and response.json()["errorCode"] == "DATA_CONFLICT"
    assert snapshot(setup) == before
    assert client.get("/nadreego/shop/admin", headers=headers).status_code == 200


def test_demotion_uses_current_role_and_removes_only_former_primary(client, signin, setup):
    former_primary = signin()
    assert client.post("/nadreego/admin/roleChange", headers=former_primary,
                       json={"adminId": "general"}).status_code == 200
    response = client.delete(PATH, headers=former_primary)
    assert response.status_code == 200 and response.json()["scope"] == "SELF"
    mapping = setup["db"].table("MSP_ADMIN_ROLE")
    with setup["engine"].connect() as conn:
        assert set(conn.scalars(select(mapping.c.role_code).where(mapping.c.admin_id == "general"))) == {PRIMARY}
        assert set(conn.scalars(select(mapping.c.role_code).where(mapping.c.admin_id == "general2"))) == {GENERAL}


def test_promoted_primary_removes_everyone_including_self(client, signin):
    primary, promoted = signin(), signin("general")
    assert client.post("/nadreego/admin/roleChange", headers=primary,
                       json={"adminId": "general"}).status_code == 200
    response = client.delete(PATH, headers=promoted)
    assert response.status_code == 200 and response.json()["scope"] == "SUBTREE"
    assert response.json()["deletedAdminCount"] == 3
    assert response.json()["deletedSpotCount"] == 2


@pytest.mark.parametrize("admin", ["general", "primary"])
def test_chat_failure_keeps_all_sql_accounts_roles_and_sessions(client, signin, setup, monkeypatch, admin):
    headers = signin(admin, fcmToken="current-device")
    before = snapshot(setup)
    calls = []

    def fail(request, admin_id):
        calls.append(admin_id)
        if admin == "general" or len(calls) == 2:
            raise Problem(503, "CHAT_SYNC_FAILED")

    monkeypatch.setattr("app.chat.revoke_admin_chat", fail)
    response = client.delete(PATH, headers=headers)
    assert response.status_code == 503 and response.json()["errorCode"] == "CHAT_SYNC_FAILED"
    assert snapshot(setup) == before
    assert client.get("/nadreego/shop/admin", headers=headers).status_code == 200


def test_general_cannot_select_another_target_or_escalate_scope(client, signin, setup):
    own, primary = signin("general"), signin()
    response = client.request("DELETE", PATH + "?adminId=primary&scope=SPOT", headers=own,
                              json={"adminId": "primary", "scope": "SPOT"})
    assert response.status_code == 200 and response.json()["scope"] == "SELF"
    assert response.json()["deletedAdminCount"] == 1
    assert client.get("/nadreego/shop/admin", headers=primary).status_code == 200


def test_no_auth_or_revoked_session_cannot_delete(client, signin, setup):
    assert client.delete(PATH).status_code == 401
    expired = signin()
    signin()
    before = snapshot(setup)
    assert client.delete(PATH, headers=expired).status_code == 401
    assert snapshot(setup) == before


def test_missing_direct_scope_cannot_delete(client, signin, setup):
    headers = signin()
    scope = setup["db"].table("MSP_ADMIN_SPOT_SCOPE")
    with setup["engine"].begin() as conn:
        conn.execute(delete(scope).where(scope.c.admin_id == "primary"))
    before = snapshot(setup)
    response = client.delete(PATH, headers=headers)
    assert response.status_code == 403 and response.json()["errorCode"] == "SPOT_ACCESS_DENIED"
    assert snapshot(setup) == before


def test_openapi_documents_both_deletion_scopes(client):
    spec = client.get("/openapi.json").json()
    operation = spec["paths"][PATH]["delete"]
    assert "requestBody" not in operation
    examples = operation["responses"]["200"]["content"]["application/json"]["examples"]
    assert examples["general"]["value"]["scope"] == "SELF"
    assert examples["primary"]["value"]["scope"] == "SUBTREE"
    assert examples["primary"]["value"]["deletedAdminCount"] == 4
    assert examples["primary"]["value"]["deletedSpotCount"] == 2
