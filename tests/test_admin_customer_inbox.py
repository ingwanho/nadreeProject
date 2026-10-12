from datetime import timedelta

from sqlalchemy import select

from app.rental_schema import metadata
from app.security import now


def seed(setup):
    metadata.create_all(setup["engine"])
    with setup["engine"].begin() as conn:
        conn.execute(metadata.tables["MSP_RENTAL_USER"].insert().values(
            uid_token="inbox-customer", name="Test customer", nationality="KR", passport_img_key="private-secret"))
        conn.execute(metadata.tables["MSP_RESERVATION"].insert().values(
            reservation_id="inbox-booking", uid_token="inbox-customer", spot_master_id="root", model_id="model",
            start_datetime=now() + timedelta(days=3), end_datetime=now() + timedelta(days=5),
            reservation_status="REQUESTED"))
        conn.execute(metadata.tables["MSP_RENTAL_NOTIFICATION"].insert().values(
            spot_master_id="root", event_type="RESERVATION_REQUESTED", target_type="RESERVATION",
            target_id="inbox-booking", event_key="test-request", created_at=now()))


def test_admin_customer_views_are_scoped_and_hide_private_fields(setup, signin):
    seed(setup)
    client = setup["client"]
    headers = signin("general")
    listing = client.get("/nadreego/customers", headers=headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()["items"] == [{"customerId": "inbox-customer", "name": "Test customer", "usageStatus": "ACTIVE"}]
    detail = client.get("/nadreego/customers/inbox-customer", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["customer"]["contact"] is None
    assert "passport" not in detail.text and "private-secret" not in detail.text
    history = client.get("/nadreego/customers/inbox-customer/history", headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["reservationId"] == "inbox-booking"
    outsider = signin("outsider")
    assert client.get("/nadreego/customers", headers=outsider).json()["items"] == []
    assert client.get("/nadreego/customers/inbox-customer", headers=outsider).status_code == 404
    assert client.get("/nadreego/customers/inbox-customer/history", headers=outsider).status_code == 404


def test_notification_read_is_shared_idempotent_and_scoped(setup, signin):
    seed(setup)
    client = setup["client"]
    general, primary, outsider = signin("general"), signin(), signin("outsider")
    path = "/nadreego/notifications"
    count = client.get(path + "/unread-count", headers=general, params={"shopId": "root"})
    assert count.json()["unreadCount"] == 1, count.text
    listing = client.get(path, headers=general, params={"shopId": "root"})
    ident = listing.json()["items"][0]["notificationId"]
    read_path = path + "/" + str(ident) + "/read"
    assert client.post(read_path, headers=outsider).status_code == 404
    first = client.post(read_path, headers=general)
    second = client.post(read_path, headers=primary)
    assert first.status_code == second.status_code == 200
    assert first.json()["readAt"] == second.json()["readAt"]
    assert client.get(path + "/unread-count", headers=primary, params={"shopId": "root"}).json()["unreadCount"] == 0


def test_notification_event_is_deduplicated(setup):
    from app.notifications import record_notification
    from sqlalchemy.orm import Session
    seed(setup)
    with Session(setup["engine"]) as session, session.begin():
        for _ in range(2):
            record_notification(setup["db"], session, "root", "RESERVATION_REQUESTED", "RESERVATION", "inbox-booking", "test-request")
    with setup["engine"].connect() as conn:
        assert len(conn.execute(select(metadata.tables["MSP_RENTAL_NOTIFICATION"])).all()) == 1
