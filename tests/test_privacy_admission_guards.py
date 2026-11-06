import secrets
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.errors import Problem
from app.main import create_app
from app.security import GENERAL, PRIMARY
from test_account_deletions import privacy, process, submit


def test_legacy_subtree_delete_preserves_a_pending_member_privacy_request(privacy, signin):
    ctx = privacy
    own, upper = signin("general"), signin()
    accepted, _, _, _ = submit(ctx, own)
    assert accepted.status_code == 202
    revoked = list(ctx["revoked"])

    response = ctx["client"].delete("/nadreego/admin/account", headers=upper)
    assert response.status_code == 409
    assert response.json()["errorCode"] == "DELETION_REQUEST_IN_PROGRESS"
    assert ctx["revoked"] == revoked
    mapping = ctx["db"].table("MSP_ADMIN_ROLE")
    with ctx["engine"].connect() as connection:
        assert GENERAL in connection.scalars(select(mapping.c.role_code).where(mapping.c.admin_id == "general"))
        assert PRIMARY in connection.scalars(select(mapping.c.role_code).where(mapping.c.admin_id == "primary"))
    assert ctx["client"].get("/nadreego/shop/admin", headers=own).status_code == 200
    assert process(ctx)["completed"] == 1


@pytest.fixture
def branch_accounts(privacy, signin, applicant):
    ctx, upper = privacy, signin()
    created = ctx["client"].post("/api/v1/organizations/spots", headers=upper, json={
        "spot_name": "Closing descendant", "unit_type": "region", "parent_spot_id": "root",
        "email": "shop@example.com", "address": "Test address", "lat": -8.6, "lng": 115.2})
    assert created.status_code == 200
    ident = created.json()["spot_id"]
    applicant("branch-primary", ident, primary_spot_master_id=ident, contract_id="CT1")
    with ctx["engine"].begin() as connection:
        connection.execute(ctx["db"].table("MSP_ADMIN_ROLE").insert().values(
            admin_id="branch-primary", role_code=PRIMARY))
        connection.execute(ctx["db"].table("MSP_ADMIN_SPOT_SCOPE").insert().values(
            admin_id="branch-primary", spot_master_id=ident, access_type="manage"))
    return ctx, upper, ident, signin("branch-primary")


@pytest.fixture
def closing_descendant(branch_accounts):
    ctx, upper, ident, branch = branch_accounts
    accepted, _, _, _ = submit(ctx, branch)
    assert accepted.status_code == 202
    return ctx, upper, ident


@pytest.mark.parametrize("operation", ["profile_update", "create_child"])
def test_ancestor_cannot_mutate_a_closing_descendant(closing_descendant, operation):
    ctx, upper, ident = closing_descendant
    master = ctx["db"].table("MSP_SPOT_MASTER")
    with ctx["engine"].connect() as connection:
        count = connection.scalar(select(func.count()).select_from(master))
        name = connection.scalar(select(master.c.spot_name).where(master.c.spot_master_id == ident))
    if operation == "profile_update":
        response = ctx["client"].post("/nadreego/shop/update", headers=upper,
            json={"spotMasterId": ident, "shopName": "Changed after deletion request"})
    else:
        response = ctx["client"].post("/api/v1/organizations/spots", headers=upper, json={
            "spot_name": "New child", "unit_type": "local", "parent_spot_id": ident,
            "email": "shop@example.com", "address": "Test address", "lat": -8.6, "lng": 115.2})
    assert response.status_code == 409
    assert response.json()["errorCode"] == "SHOP_CLOSING"
    with ctx["engine"].connect() as connection:
        assert connection.scalar(select(func.count()).select_from(master)) == count
        assert connection.scalar(select(master.c.spot_name).where(master.c.spot_master_id == ident)) == name
    assert ctx["client"].get("/nadreego/shop/profile", headers=upper,
        params={"spotMasterId": ident}).status_code == 200
    assert ctx["client"].post("/nadreego/shop/update", headers=upper,
        json={"shopName": "Open ancestor"}).status_code == 200


def test_privacy_cors_allows_request_headers_and_exposes_retry_after():
    origin = "https://example.invalid"
    app = create_app(Settings(_env_file=None, env="test", cors_origins=origin))
    with TestClient(app) as client:
        response = client.options("/nadreego/admin/account-deletion-requests", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key,deletion-receipt-token"})
        assert response.status_code == 200
        allowed = response.headers["access-control-allow-headers"].lower()
        assert "idempotency-key" in allowed and "deletion-receipt-token" in allowed
        actual = client.get("/health/live", headers={"Origin": origin})
        assert "retry-after" in actual.headers["access-control-expose-headers"].lower()


@pytest.mark.parametrize("first", ["general", "primary"])
def test_self_and_subtree_requests_cannot_overlap(privacy, signin, first):
    ctx = privacy
    own, upper = signin("general"), signin()
    first_headers, other_headers = (own, upper) if first == "general" else (upper, own)
    revoked = list(ctx["revoked"])
    accepted, _, _, _ = submit(ctx, first_headers)
    assert accepted.status_code == 202
    blocked, _, _, _ = submit(ctx, other_headers)
    assert blocked.status_code == 409
    assert blocked.json()["errorCode"] == "DELETION_SCOPE_IN_PROGRESS"
    assert len(list(ctx["store"].pending())) == 1
    assert ctx["revoked"] == revoked


@pytest.mark.parametrize("first", ["ancestor", "descendant"])
def test_overlapping_subtree_requests_are_rejected_in_either_order(branch_accounts, first):
    ctx, upper, _, branch = branch_accounts
    first_headers, other_headers = (upper, branch) if first == "ancestor" else (branch, upper)
    accepted, _, _, _ = submit(ctx, first_headers)
    assert accepted.status_code == 202
    blocked, _, _, _ = submit(ctx, other_headers)
    assert blocked.status_code == 409
    assert blocked.json()["errorCode"] == "DELETION_SCOPE_IN_PROGRESS"
    assert len(list(ctx["store"].pending())) == 1


def test_saved_request_blocks_overlap_even_when_sql_gate_was_not_committed(branch_accounts):
    ctx, upper, ident, branch = branch_accounts
    create = ctx["store"].create

    def lost_acknowledgement(row):
        create(row)
        raise RuntimeError("isolated acknowledgement loss")

    ctx["store"].create = lost_acknowledgement
    accepted, _, _, _ = submit(ctx, branch)
    assert accepted.status_code == 503
    assert accepted.json()["errorCode"] == "DELETION_OUTCOME_UNKNOWN"
    ctx["store"].create = create
    rent = ctx["db"].table("MSP_SPOT_RENT")
    with ctx["engine"].connect() as connection:
        assert connection.scalar(select(rent.c.deletion_request_id).where(rent.c.spot_master_id == ident)) is None
    blocked, _, _, _ = submit(ctx, upper)
    assert blocked.status_code == 409
    assert blocked.json()["errorCode"] == "DELETION_SCOPE_IN_PROGRESS"
    assert len(list(ctx["store"].pending())) == 1


def test_operator_intake_cannot_overlap_an_existing_member_request(privacy, signin):
    from app.account_deletion_ops import act
    ctx = privacy
    accepted, _, _, _ = submit(ctx, signin("general"))
    assert accepted.status_code == 202
    with pytest.raises(Problem) as error:
        act(ctx["db"], ctx["settings"], ctx["store"], "register", admin_id="primary",
            email="primary@example.com", idempotency=str(uuid4()), receipt=secrets.token_urlsafe(32),
            operator="isolated-operator", evidence="isolated identity verification")
    assert error.value.code == "DELETION_SCOPE_IN_PROGRESS"
    assert len(list(ctx["store"].pending())) == 1


def test_unrelated_self_requests_can_still_complete(privacy, signin):
    ctx = privacy
    first, _, _, _ = submit(ctx, signin("general"))
    second, _, _, _ = submit(ctx, signin("general2"))
    assert first.status_code == second.status_code == 202
    assert process(ctx)["completed"] == 2
