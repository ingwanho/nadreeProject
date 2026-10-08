from datetime import timedelta, timezone

import pytest

from sqlalchemy import select

from app.rental_schema import metadata as rental_metadata
from app.firebase_auth import CustomerFirebaseAuth
from app.security import decode_user_access, fingerprint, now


def rental_tables(setup):
    rental_metadata.create_all(setup["engine"])
    return {name: setup["db"].table(name) for name in ("MSP_RENTAL_USER", "MSP_RENTAL_USER_REFRESH_TOKEN")}


def login(client, uid):
    response = client.post("/api/v1/nadree/user/login", json={"UID": uid})
    assert response.status_code == 200, response.text
    data = response.json()
    return {"Authorization": "Bearer " + data["accessToken"], "X-Refresh-Token": data["refreshToken"]}, data


def test_nadri_login_issues_a_separate_refresh_token(setup):
    tables = rental_tables(setup)
    headers, data = login(setup["client"], "user-refresh-1")

    assert headers["X-Refresh-Token"].startswith("nadri.rt.")
    assert data["refreshToken"] == headers["X-Refresh-Token"]
    with setup["engine"].connect() as connection:
        row = connection.execute(select(tables["MSP_RENTAL_USER_REFRESH_TOKEN"])).mappings().one()
    assert row["uid_token"] == "user-refresh-1"
    assert row["token_hash"] == fingerprint(headers["X-Refresh-Token"])


def test_nadri_app_fcm_token_is_preserved_when_logout_header_is_omitted(setup):
    tables = rental_tables(setup)
    response = setup["client"].post("/api/v1/nadree/user/login", json={
        "UID": "user-fcm", "fcmToken": "customer-device-token"})
    assert response.status_code == 200, response.text
    data = response.json()
    headers = {"Authorization": "Bearer " + data["accessToken"], "X-Refresh-Token": data["refreshToken"]}

    with setup["engine"].connect() as connection:
        row = connection.execute(select(tables["MSP_RENTAL_USER"])).mappings().one()
    assert row["fcm_token"] == "customer-device-token"
    assert row["fcm_token_updated_at"] is not None

    response = setup["client"].patch("/api/v1/nadree/user/profile", headers=headers,
                                      json={"fcmToken": "customer-device-token-2"})
    assert response.status_code == 200, response.text
    assert setup["client"].post("/api/v1/nadree/user/logout", headers=headers).status_code == 200
    with setup["engine"].connect() as connection:
        row = connection.execute(select(tables["MSP_RENTAL_USER"])).mappings().one()
    assert row["fcm_token"] == "customer-device-token-2"


def test_nadri_profile_get_and_logout_clears_matching_device_token(setup):
    tables = rental_tables(setup)
    response = setup["client"].post("/api/v1/nadree/user/login", json={
        "UID": "user-fcm-get", "fcmToken": "customer-device-token"})
    assert response.status_code == 200, response.text
    data = response.json()
    headers = {"Authorization": "Bearer " + data["accessToken"],
               "X-Refresh-Token": data["refreshToken"]}

    profile = setup["client"].get("/api/v1/nadree/user/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["user"]["uidToken"] == "user-fcm-get"

    logout = setup["client"].post("/api/v1/nadree/user/logout",
                                   headers={**headers, "X-FCM-Token": "customer-device-token"})
    assert logout.status_code == 200, logout.text
    with setup["engine"].connect() as connection:
        row = connection.execute(select(tables["MSP_RENTAL_USER"])).mappings().one()
    assert row["fcm_token"] is None


def test_nadri_refresh_rotates_and_rejects_the_previous_token(setup):
    rental_tables(setup)
    headers, _ = login(setup["client"], "user-refresh-2")
    old_refresh = headers["X-Refresh-Token"]

    response = setup["client"].post("/api/v1/nadree/user/refresh", headers={"X-Refresh-Token": old_refresh})
    assert response.status_code == 200, response.text
    new_refresh = response.json()["refreshToken"]
    assert new_refresh != old_refresh
    assert setup["client"].post("/api/v1/nadree/user/refresh",
                                 headers={"X-Refresh-Token": old_refresh}).status_code == 401
    assert setup["client"].post("/api/v1/nadree/user/refresh",
                                 headers={"X-Refresh-Token": new_refresh}).status_code == 200


def test_nadri_login_keeps_one_active_refresh_token_per_uid(setup):
    tables = rental_tables(setup)
    first, _ = login(setup["client"], "user-refresh-3")
    second, _ = login(setup["client"], "user-refresh-3")

    assert setup["client"].post("/api/v1/nadree/user/refresh", headers={
        "X-Refresh-Token": first["X-Refresh-Token"]}).status_code == 401
    assert setup["client"].post("/api/v1/nadree/user/refresh", headers={
        "X-Refresh-Token": second["X-Refresh-Token"]}).status_code == 200
    with setup["engine"].connect() as connection:
        rows = connection.execute(select(tables["MSP_RENTAL_USER_REFRESH_TOKEN"])).mappings().all()
    assert len([row for row in rows if row["revoked_at"] is None]) == 1


def test_nadri_logout_revokes_access_and_refresh_tokens(setup, monkeypatch):
    rental_tables(setup)
    headers, _ = login(setup["client"], "user-refresh-4")
    response = setup["client"].post("/api/v1/nadree/user/logout", headers=headers)
    assert response.status_code == 200, response.text
    assert setup["client"].post("/api/v1/nadree/user/refresh", headers={
        "X-Refresh-Token": headers["X-Refresh-Token"]}).status_code == 401
    assert setup["client"].patch("/api/v1/nadree/user/profile", headers={
        "Authorization": headers["Authorization"]}, json={"NAME": "로그아웃 후"}).status_code == 401
    # A new authentication must be in a later second than session revocation.
    later = now() + timedelta(seconds=1)
    monkeypatch.setattr("app.customer_rentals.now", lambda: later)
    fresh, _ = login(setup["client"], "user-refresh-4")
    assert setup["client"].post("/api/v1/nadree/user/refresh", headers={
        "X-Refresh-Token": fresh["X-Refresh-Token"]}).status_code == 200


def test_nadri_logout_keeps_access_only_compatibility(setup):
    rental_tables(setup)
    headers, _ = login(setup["client"], "user-refresh-compat")
    response = setup["client"].post("/api/v1/nadree/user/logout", headers={
        "Authorization": headers["Authorization"]})
    assert response.status_code == 200, response.text
    assert setup["client"].post("/api/v1/nadree/user/refresh", headers={
        "X-Refresh-Token": headers["X-Refresh-Token"]}).status_code == 401


def test_nadri_account_deletion_is_unconditional_and_revokes_sessions(setup):
    tables = rental_tables(setup)
    headers, _ = login(setup["client"], "user-delete")
    response = setup["client"].delete("/api/v1/nadree/user/account", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "success", "deleted": True}
    assert setup["client"].get("/api/v1/nadree/user/profile", headers=headers).status_code == 401
    assert setup["client"].post("/api/v1/nadree/user/refresh", headers={
        "X-Refresh-Token": headers["X-Refresh-Token"]}).status_code == 401
    with setup["engine"].connect() as connection:
        row = connection.execute(select(tables["MSP_RENTAL_USER"])).mappings().one()
    assert row["name"] is None and row["fcm_token"] is None and row["user_access_revoked_at"] is not None


def test_nadri_logout_rejects_a_refresh_token_from_another_user(setup):
    rental_tables(setup)
    first, _ = login(setup["client"], "user-refresh-5")
    second, _ = login(setup["client"], "user-refresh-6")
    response = setup["client"].post("/api/v1/nadree/user/logout", headers={
        "Authorization": first["Authorization"], "X-Refresh-Token": second["X-Refresh-Token"]})
    assert response.status_code == 401 and response.json()["errorCode"] == "TOKEN_PAIR_MISMATCH"


def test_admin_and_nadri_refresh_tokens_are_not_cross_usable(setup, signin):
    rental_tables(setup)
    customer, _ = login(setup["client"], "user-refresh-separated")
    admin = signin()

    assert setup["client"].post("/api/v1/nadree/user/refresh", headers={
        "X-Refresh-Token": admin["X-Refresh-Token"]}).status_code == 401
    assert setup["client"].get("/nadreego/admin/refresh", headers={
        "X-Refresh-Token": customer["X-Refresh-Token"]}).status_code == 401


@pytest.mark.parametrize("action", ["delete", "logout"])
def test_revocation_rejects_old_firebase_authentication_and_allows_reauthentication(setup, monkeypatch, action):
    tables = rental_tables(setup)
    cutoff = now().replace(microsecond=0)
    seconds = int(cutoff.replace(tzinfo=timezone.utc).timestamp())
    claims = {"uid": "reauth-user", "auth_time": seconds - 60}
    verifier = CustomerFirebaseAuth(setup["settings"], verify_fn=lambda token: dict(claims))
    deleted = []
    monkeypatch.setattr(verifier, "delete_uid", lambda uid: deleted.append(uid))
    setup["app"].state.customer_auth = verifier
    monkeypatch.setattr("app.customer_rentals.now", lambda: cutoff)

    def authenticate():
        return setup["client"].post("/api/v1/nadree/user/login", headers={"Authorization": "Bearer firebase-token"},
                                    json={"UID": claims["uid"], "fcmToken": "test-device"})

    initial = authenticate()
    assert initial.status_code == 200, initial.text
    data = initial.json()
    assert decode_user_access(setup["settings"], data["accessToken"])["auth_time"] == seconds - 60
    headers = {"Authorization": "Bearer " + data["accessToken"], "X-Refresh-Token": data["refreshToken"]}
    response = (setup["client"].delete("/api/v1/nadree/user/account", headers=headers) if action == "delete"
                else setup["client"].post("/api/v1/nadree/user/logout", headers=headers))
    assert response.status_code == 200, response.text
    assert deleted == (["reauth-user"] if action == "delete" else [])
    for auth_time in (seconds - 60, seconds):
        claims["auth_time"] = auth_time
        rejected = authenticate()
        assert rejected.status_code == 401
        assert rejected.json()["errorCode"] == "FIREBASE_REAUTHENTICATION_REQUIRED"
    with setup["engine"].connect() as connection:
        sessions = connection.execute(select(tables["MSP_RENTAL_USER_REFRESH_TOKEN"])).mappings().all()
        assert len(sessions) == 1 and sessions[0]["revoked_at"] is not None
        if action == "delete":
            assert connection.scalar(select(tables["MSP_RENTAL_USER"].c.fcm_token)) is None

    # Same UID is accepted only after a genuinely newer verified authentication.
    claims["auth_time"] = seconds + 1
    monkeypatch.setattr("app.customer_rentals.now", lambda: cutoff + timedelta(seconds=1))
    fresh = authenticate()
    assert fresh.status_code == 200, fresh.text
    assert decode_user_access(setup["settings"], fresh.json()["accessToken"])["auth_time"] == seconds + 1
    assert setup["client"].get("/api/v1/nadree/user/profile", headers={
        "Authorization": "Bearer " + fresh.json()["accessToken"]}).status_code == 200
    assert setup["client"].post("/api/v1/nadree/user/refresh", headers={
        "X-Refresh-Token": fresh.json()["refreshToken"]}).status_code == 200
    assert setup["client"].get("/api/v1/nadree/user/profile", headers=headers).status_code == 401
    assert setup["client"].post("/api/v1/nadree/user/refresh", headers=headers).status_code == 401
    assert setup["client"].post("/api/v1/nadree/rental/request/cancel", headers=headers,
                                json={"reservationId": "any-booking"}).status_code == 401

    claims["uid"] = "new-registration-uid"
    registered = authenticate()
    assert registered.status_code == 200, registered.text
    assert registered.json()["isNewUser"] is True
