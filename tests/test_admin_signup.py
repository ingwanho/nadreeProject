from sqlalchemy import select


def test_public_signup_creates_account_and_pending_request(client, setup, signin):
    result = client.post("/nadreego/admin/signup", json={
        "loginId": "new-manager", "email": "new-manager@example.com", "password": "Test-password-123!",
        "name": "New manager", "representativeEmail": "primary@example.com",
    })
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["requestStatus"] == "REQUESTED"
    admins = setup["db"].table("MSP_ADMIN")
    requests = setup["db"].table("MSP_RENTAL_ADMIN_REQUEST")
    with setup["engine"].connect() as conn:
        admin = conn.execute(select(admins).where(admins.c.admin_id == body["adminId"])).mappings().one()
        request = conn.execute(select(requests).where(requests.c.request_id == body["requestId"])).mappings().one()
    assert admin["login_id"] == "new-manager"
    assert admin["admin_name"] == "New manager"
    assert admin["account_type"] == "manager" and admin["mfa_method"] == "none"
    assert admin["is_active"] == 1 and admin["contract_id"] is None and admin["primary_spot_master_id"] is None
    assert admin["password_hash"] != "Test-password-123!" and request["status"] == "REQUESTED"
    approved = client.post("/nadreego/shop/adminRequestAction", headers=signin(),
                           json={"email": "new-manager@example.com", "action": "APPROVE"})
    assert approved.status_code == 200, approved.text
    assert client.post("/nadreego/admin/login", json={
        "email": "new-manager", "password": "Test-password-123!"}).status_code == 200


def test_child_invite_signup_is_approved_with_explicit_target(client, setup, signin):
    created = client.post("/api/v1/organizations/spots", headers=signin(), json={
        "spot_name": "Child branch", "unit_type": "spot", "parent_spot_id": "root"})
    assert created.status_code == 200, created.text
    spot = created.json()
    result = client.post("/nadreego/admin/signup", json={
        "loginId": "child-manager", "email": "child-manager@example.com", "password": "Test-password-123!",
        "name": "Child manager", "representativeEmail": "primary@example.com", "inviteCode": spot["inviteCode"],
    })
    assert result.status_code == 201, result.text
    approved = client.post("/nadreego/shop/adminRequestAction", headers=signin(), json={
        "email": "child-manager@example.com", "action": "APPROVE", "spotMasterId": spot["spot_id"]})
    assert approved.status_code == 200, approved.text
    rent = setup["db"].table("MSP_SPOT_RENT")
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(rent.c.invite_code).where(rent.c.spot_master_id == spot["spot_id"])) is None
