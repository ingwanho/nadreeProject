import pytest
from sqlalchemy import delete, event, select, update
from sqlalchemy.exc import IntegrityError

from app.security import GENERAL, PRIMARY, now

LIST = "/nadreego/shop/adminRequest"
ACTION = "/nadreego/shop/adminRequestAction"


def state(setup, ident="applicant"):
    db = setup["db"]
    with setup["engine"].connect() as conn:
        pending, admins, mapping, scope = [db.table(name) for name in
            ["MSP_RENTAL_ADMIN_REQUEST", "MSP_ADMIN", "MSP_ADMIN_ROLE", "MSP_ADMIN_SPOT_SCOPE"]]
        request = dict(conn.execute(select(pending).where(pending.c.admin_id == ident)).mappings().one())
        account = dict(conn.execute(select(admins).where(admins.c.admin_id == ident)).mappings().one())
        roles = set(conn.scalars(select(mapping.c.role_code).where(mapping.c.admin_id == ident)))
        scopes = conn.execute(select(scope).where(scope.c.admin_id == ident)).mappings().all()
    return request, account, roles, [dict(row) for row in scopes]


def test_list_only_current_spot_pending_requests(client, signin, applicant, setup):
    applicant()
    applicant("foreign-applicant", "foreign")
    applicant("child-applicant", "child")
    email = applicant("rejected")
    headers = signin()
    assert client.post(ACTION, headers=headers, json={"email": email, "action": "REJECT"}).status_code == 200
    assert client.get(LIST, headers=headers).json() == {
        "status": "success", "admins": [{"email": "applicant@example.com", "name": "applicant"}]}
    assert client.get(LIST, headers=signin("outsider")).json()["admins"] == [
        {"email": "foreign-applicant@example.com", "name": "foreign-applicant"}]


def test_approve_grants_general_membership_and_records_reviewer(client, signin, applicant, setup):
    email = applicant()
    assert client.post("/nadreego/admin/login", json={"email": email, "password": "Test-password-123!"}).status_code == 403
    result = client.post(ACTION, headers=signin(), json={"email": email.upper(), "action": "APPROVE"})
    assert result.status_code == 200 and result.json() == {"status": "success"}
    pending, account, granted, scopes = state(setup)
    assert pending["status"] == "APPROVED" and pending["reviewed_by_admin_id"] == "primary"
    assert pending["reviewed_at"] >= pending["requested_at"]
    assert account["primary_spot_master_id"] == "root" and account["contract_id"] == "CT1"
    assert granted == {GENERAL} and scopes[0]["access_type"] == "manage"
    assert scopes[0]["spot_master_id"] == "root" and scopes[0]["granted_by"] == "primary"
    new_headers = signin("applicant")
    assert client.get("/nadreego/shop/admin", headers=new_headers).status_code == 200
    assert client.get(LIST, headers=new_headers).status_code == 403


def test_reject_records_only_request_without_changing_shared_account(client, signin, applicant, setup):
    email = applicant(is_active=0)
    before = state(setup)
    assert client.post(ACTION, headers=signin(), json={"email": email, "action": "REJECT"}).json() == {"status": "success"}
    after = state(setup)
    assert after[0]["status"] == "REJECTED" and after[0]["reviewed_by_admin_id"] == "primary"
    assert after[1:] == before[1:]


@pytest.mark.parametrize("first", ["APPROVE", "REJECT"])
@pytest.mark.parametrize("second", ["APPROVE", "REJECT"])
def test_processed_request_cannot_be_processed_again(client, signin, applicant, setup, first, second):
    email, headers = applicant(), signin()
    assert client.post(ACTION, headers=headers, json={"email": email, "action": first}).status_code == 200
    before = state(setup)
    result = client.post(ACTION, headers=headers, json={"email": email, "action": second})
    assert result.status_code == 409 and result.json()["errorCode"] == "ADMIN_REQUEST_ALREADY_PROCESSED"
    assert state(setup) == before


@pytest.mark.parametrize("spot", ["foreign", "child"])
def test_other_spot_request_not_found_and_unchanged(client, signin, applicant, setup, spot):
    email = applicant(spot=spot)
    before = state(setup)
    result = client.post(ACTION, headers=signin(), json={"email": email, "action": "APPROVE"})
    assert result.status_code == 404 and result.json()["errorCode"] == "ADMIN_REQUEST_NOT_FOUND"
    assert state(setup) == before


@pytest.mark.parametrize("values,code", [
    ({"is_active": 0}, "APPLICANT_ACCOUNT_UNAVAILABLE"),
    ({"primary_spot_master_id": "foreign"}, "APPLICANT_MEMBERSHIP_CONFLICT"),
    ({"contract_id": "CT2"}, "APPLICANT_MEMBERSHIP_CONFLICT"),
])
def test_invalid_account_cannot_be_reactivated_or_transferred(client, signin, applicant, setup, values, code):
    email = applicant(**values)
    before = state(setup)
    response = client.post(ACTION, headers=signin(), json={"email": email, "action": "APPROVE"})
    assert response.status_code == 409 and response.json()["errorCode"] == code
    assert state(setup) == before


@pytest.mark.parametrize("value", [None, "changed@example.com"])
def test_changed_email_cannot_approve_different_identity(client, signin, applicant, setup, value):
    email = applicant()
    table = setup["db"].table("MSP_ADMIN")
    with setup["engine"].begin() as conn:
        conn.execute(update(table).where(table.c.admin_id == "applicant").values(email=value))
    result = client.post(ACTION, headers=signin(), json={"email": email, "action": "APPROVE"})
    assert result.status_code == 409 and result.json()["errorCode"] == "APPLICANT_EMAIL_CHANGED"
    assert state(setup)[0]["status"] == "REQUESTED"


@pytest.mark.parametrize("code", [GENERAL, PRIMARY])
def test_existing_rental_role_not_replaced(client, signin, applicant, setup, code):
    email = applicant(primary_spot_master_id="root", contract_id="CT1")
    table = setup["db"].table("MSP_ADMIN_ROLE")
    with setup["engine"].begin() as conn:
        conn.execute(table.insert().values(admin_id="applicant", role_code=code, expires_at=now()))
    before = state(setup)
    response = client.post(ACTION, headers=signin(), json={"email": email, "action": "APPROVE"})
    assert response.status_code == 409 and response.json()["errorCode"] == "APPLICANT_ALREADY_RENTAL_ADMIN"
    assert state(setup) == before


def test_preserves_web_roles_and_existing_scope(client, signin, applicant, setup):
    email = applicant(primary_spot_master_id="root", contract_id="CT1")
    mapping, scope = setup["db"].table("MSP_ADMIN_ROLE"), setup["db"].table("MSP_ADMIN_SPOT_SCOPE")
    with setup["engine"].begin() as conn:
        conn.execute(mapping.insert().values(admin_id="applicant", role_code="viewer"))
        conn.execute(scope.insert().values(admin_id="applicant", spot_master_id="root", access_type="manage"))
    before = state(setup)
    assert client.post(ACTION, headers=signin(), json={"email": email, "action": "APPROVE"}).status_code == 200
    after = state(setup)
    assert after[2] == {GENERAL, "viewer"} and after[3] == before[3]
    assert after[1]["password_hash"] == before[1]["password_hash"]


def test_missing_general_role_blocks_approval(client, signin, applicant, setup):
    email, headers = applicant(), signin()
    table = setup["db"].table("MSP_ROLE")
    with setup["engine"].begin() as conn:
        conn.execute(update(table).where(table.c.role_code == GENERAL).values(is_active=0))
    before = state(setup)
    result = client.post(ACTION, headers=headers, json={"email": email, "action": "APPROVE"})
    assert result.status_code == 503 and result.json()["errorCode"] == "RENTAL_ROLE_NOT_CONFIGURED"
    assert state(setup) == before


def test_request_failure_rolls_back_membership_and_role(client, signin, applicant, setup):
    email, headers = applicant(), signin()
    before = state(setup)

    def fail_request_write(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE") and "MSP_RENTAL_ADMIN_REQUEST" in statement:
            raise IntegrityError("isolated test failure", {}, Exception("test"))

    event.listen(setup["engine"], "before_cursor_execute", fail_request_write)
    try:
        response = client.post(ACTION, headers=headers, json={"email": email, "action": "APPROVE"})
    finally:
        event.remove(setup["engine"], "before_cursor_execute", fail_request_write)
    assert response.status_code == 409 and state(setup) == before


@pytest.mark.parametrize("field", ["email", "admin_id"])
def test_duplicate_request_rejected_by_storage(setup, applicant, field):
    applicant()
    table = setup["db"].table("MSP_RENTAL_ADMIN_REQUEST")
    values = {"request_id": "duplicate", "spot_master_id": "root", "email": "different@example.com", "admin_id": "different"}
    values[field] = "applicant@example.com" if field == "email" else "applicant"
    with pytest.raises(IntegrityError), setup["engine"].begin() as conn:
        conn.execute(table.insert().values(**values))


def test_missing_account_can_be_rejected_but_not_approved(client, signin, applicant, setup):
    email, headers = applicant(), signin()
    table = setup["db"].table("MSP_ADMIN")
    with setup["engine"].begin() as conn:
        conn.execute(delete(table).where(table.c.admin_id == "applicant"))
    assert client.get(LIST, headers=headers).json()["admins"] == [{"email": email, "name": None}]
    result = client.post(ACTION, headers=headers, json={"email": email, "action": "APPROVE"})
    assert result.status_code == 409 and result.json()["errorCode"] == "APPLICANT_ACCOUNT_UNAVAILABLE"
    assert client.post(ACTION, headers=headers, json={"email": email, "action": "REJECT"}).status_code == 200


@pytest.mark.parametrize("body", [
    {"email": "applicant@example.com", "action": "RESET"},
    {"email": "not-email", "action": "APPROVE"},
    {"email": "applicant@example.com", "action": "APPROVE", "role": PRIMARY},
])
def test_invalid_action_cannot_mutate_request(client, signin, applicant, setup, body):
    applicant()
    before = state(setup)
    assert client.post(ACTION, headers=signin(), json=body).status_code == 422
    assert state(setup) == before


def test_unauthenticated_requests_denied(client, applicant, setup):
    email = applicant()
    assert client.get(LIST).status_code == 401
    assert client.post(ACTION, json={"email": email, "action": "APPROVE"}).status_code == 401
    assert state(setup)[0]["status"] == "REQUESTED"
