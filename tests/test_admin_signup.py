from sqlalchemy import select


def test_public_signup_creates_account_and_pending_request(client, setup, signin):
    result = client.post("/nadreego/admin/signup", json={
        "loginId": "new-manager", "email": "new-manager@example.com", "password": "Test-password-123!",
        "name": "New manager", "representativeEmail": "primary@example.com",
    })
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["requestStatus"] == "REQUESTED"
    assert body["accountStatus"] == "PENDING_APPROVAL"
    assert client.post("/nadreego/admin/login", json={
        "email": "new-manager", "password": "Test-password-123!"}).status_code != 200
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


def test_child_invite_signup_is_primary_without_approval(client, setup, signin):
    created = client.post("/api/v1/organizations/spots", headers=signin(), json={
        "spot_name": "Child branch", "unit_type": "spot", "parent_spot_id": "root",
        "email": "shop@example.com", "address": "Test address", "lat": -8.65, "lng": 115.2})
    assert created.status_code == 200, created.text
    spot = created.json()
    result = client.post("/nadreego/admin/signup", json={
        "loginId": "child-manager", "email": "child-manager@example.com", "password": "Test-password-123!",
        "name": "Child manager", "inviteCode": spot["inviteCode"],
    })
    assert result.status_code == 201, result.text
    assert result.json()["accountStatus"] == "ACTIVE"
    assert result.json()["requestId"] is None
    assert result.json()["requestStatus"] is None
    login = client.post("/nadreego/admin/login", json={"email": "child-manager", "password": "Test-password-123!"})
    assert login.status_code == 200, login.text
    assert login.json()["admin"]["spotMasterId"] == spot["spot_id"]
    rent = setup["db"].table("MSP_SPOT_RENT")
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(rent.c.invite_code).where(rent.c.spot_master_id == spot["spot_id"])) is None
        mapping = setup["db"].table("MSP_ADMIN_ROLE")
        assert conn.scalar(select(mapping.c.role_code).where(
            mapping.c.admin_id == result.json()["adminId"])) == "rental_primary_admin"
    headers = {"Authorization": "Bearer " + login.json()["accessToken"]}
    assert client.post("/nadreego/shop/update", headers=headers,
                       json={"spotMasterId": "root", "shopName": "Forbidden"}).status_code in (403, 404)
    nested = client.post("/api/v1/organizations/spots", headers=headers, json={
        "spot_name": "Nested branch", "unit_type": "spot", "parent_spot_id": spot["spot_id"],
        "email": "nested-shop@example.com", "address": "Nested address", "lat": -8.65, "lng": 115.2})
    assert nested.status_code == 200, nested.text
    nested_signup = client.post("/nadreego/admin/signup", json={
        "loginId": "nested-manager", "email": "nested-manager@example.com", "password": "Test-password-123!",
        "name": "Nested manager", "inviteCode": nested.json()["inviteCode"]})
    assert nested_signup.status_code == 201, nested_signup.text
    assert nested_signup.json()["spotMasterId"] == nested.json()["spot_id"]
    reused = client.post("/nadreego/admin/signup", json={
        "loginId": "reuse-manager", "email": "reuse-manager@example.com", "password": "Test-password-123!",
        "name": "Reuse manager", "inviteCode": spot["inviteCode"]})
    assert reused.status_code == 404, reused.text
    assert reused.json()["errorCode"] == "INVITE_CODE_NOT_FOUND"
    pending = client.post("/nadreego/admin/signup", json={
        "loginId": "child-staff", "email": "child-staff@example.com", "password": "Test-password-123!",
        "name": "Child staff", "representativeEmail": "child-manager@example.com"})
    assert pending.status_code == 201, pending.text
    assert pending.json()["spotMasterId"] == spot["spot_id"]
    assert pending.json()["accountStatus"] == "PENDING_APPROVAL"
    approved = client.post("/nadreego/shop/adminRequestAction", headers=headers,
                           json={"email": "child-staff@example.com", "action": "APPROVE"})
    assert approved.status_code == 200, approved.text
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(mapping.c.role_code).where(
            mapping.c.admin_id == pending.json()["adminId"])) == "rental_manager"
