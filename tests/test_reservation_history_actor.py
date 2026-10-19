from datetime import date, timedelta

import pytest
from sqlalchemy import select, text

from app.security import now, sign_user_access
from app.rental_schema import metadata as rental_metadata
from test_nadri_flow import prepare_rental_schema


@pytest.fixture
def history_contract(setup):
    tables = prepare_rental_schema(setup)
    engine = setup["engine"]
    mysql = engine.dialect.name == "mysql"
    with engine.begin() as conn:
        if mysql:
            conn.execute(text("ALTER TABLE MSP_RESERVATION_HISTORY ADD CONSTRAINT fk_history_admin_test "
                              "FOREIGN KEY (changed_by) REFERENCES MSP_ADMIN(admin_id)"))
        else:
            # Mirror the production admin-only FK even though the lightweight
            # SQLite rental schema intentionally omits shared-service FKs.
            conn.execute(text("""CREATE TRIGGER history_admin_fk BEFORE INSERT ON MSP_RESERVATION_HISTORY
                WHEN NEW.changed_by IS NOT NULL AND NOT EXISTS
                    (SELECT 1 FROM MSP_ADMIN WHERE admin_id = NEW.changed_by)
                BEGIN SELECT RAISE(ABORT, 'admin history FK'); END"""))
        conn.execute(tables["MSP_RENTAL_USER"].insert().values(uid_token="history-customer"))
        conn.execute(tables["MSP_VEHICLE_MODEL"].insert().values(
            model_id="history-model", brand="Test", model_name="Test", cc=125,
            vehicle_type="SCOOTER", is_active=1))
        conn.execute(tables["MSP_RENTAL_VEHICLE"].insert().values(
            vehicle_id="history-vehicle", model_id="history-model", plate_number_full="TEST-HISTORY",
            price_type="BASIC", rental_enabled=1))
        conn.execute(tables["MSP_VEHICLE"].insert().values(vehicle_id="history-vehicle", is_active=1))
        conn.execute(tables["MSP_VEHICLE_SPOT_HISTORY"].insert().values(
            vehicle_id="history-vehicle", spot_master_id="root"))
        conn.execute(tables["MSP_VEHICLE_STATUS"].insert().values(
            vehicle_id="history-vehicle", status="AVAILABLE", status_changed_at=now()))
        conn.execute(tables["MSP_RENTAL_TIER"].insert().values(
            spot_master_id=None, price=10, min_cc=0, max_cc=1000, tier_type="BASE"))
        spot = setup["db"].table("MSP_SPOT_RENT")
        conn.execute(spot.update().where(spot.c.spot_master_id == "root").values(
            paypal_merchant_id=None, paypal_environment=None))
    try:
        yield tables
    finally:
        if mysql:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE MSP_RESERVATION_HISTORY DROP FOREIGN KEY fk_history_admin_test"))
            rental_metadata.drop_all(engine)
            for name in ("MSP_SENSOR", "MSP_VEHICLE_SPOT_HISTORY", "MSP_VEHICLE"):
                tables[name].drop(engine)


def check_customer_and_admin_history(setup, signin, tables, terminal_action):
    client = setup["client"]
    headers = {"Authorization": "Bearer " + sign_user_access(setup["settings"], "history-customer")}
    start = date.today() + timedelta(days=7)
    period = {"startDate": str(start), "returnDate": str(start + timedelta(days=2)),
              "cc": 125, "deliveryRequested": False}
    available = client.post("/api/v1/nadree/rental/availability", json=period)
    assert available.status_code == 200, available.text
    item = next(v for v in available.json()["items"] if v["shopId"] == "root")
    option = item["price"]["pricingTiers"][0]
    body = {k: v for k, v in period.items() if k != "cc"}
    body.update(spotMasterId="root", modelId="history-model", totalPrice=option["totalPrice"],
                currency="USD", priceOptionId=option["priceOptionId"])
    created = client.post("/api/v1/nadree/rental/request", headers=headers, json=body)
    assert created.status_code == 200, created.text
    ident = created.json()["reservationId"]
    assert created.json()["reservationStatus"] == "REQUESTED"
    with setup["engine"].connect() as conn:
        row = conn.execute(select(tables["MSP_RESERVATION_HISTORY"]).where(
            tables["MSP_RESERVATION_HISTORY"].c.reservation_id == ident)).mappings().one()
        assert row["changed_by"] is None
        assert row["details"] == {"actorType": "CUSTOMER", "actorId": "history-customer"}
    if terminal_action == "customer_cancel":
        result = client.post("/api/v1/nadree/rental/request/cancel", headers=headers,
                             json={"reservationId": ident, "reason": "test cancellation"})
        event, actor = "CANCELLED", None
    else:
        result = client.post("/nadreego/booking/action", headers=signin(),
                             json={"bookedNo": "BO" + ident, "action": "REJECT", "reason": "test rejection"})
        event, actor = "REJECTED", "primary"
    assert result.status_code == 200, result.text
    with setup["engine"].connect() as conn:
        h = tables["MSP_RESERVATION_HISTORY"]
        row = conn.execute(select(h).where(h.c.reservation_id == ident, h.c.event_type == event)).mappings().one()
        assert row["changed_by"] == actor
        assert row["reason"] == ("test cancellation" if actor is None else "test rejection")
        if actor is None:
            assert row["details"] == {"actorType": "CUSTOMER", "actorId": "history-customer"}


@pytest.mark.parametrize("terminal_action", ["customer_cancel", "admin_reject"])
def test_reservation_history_preserves_admin_fk(setup, signin, history_contract, terminal_action):
    check_customer_and_admin_history(setup, signin, history_contract, terminal_action)


@pytest.mark.mysql
@pytest.mark.parametrize("terminal_action", ["customer_cancel", "admin_reject"])
def test_mysql_reservation_history_preserves_admin_fk(setup, signin, history_contract, terminal_action):
    check_customer_and_admin_history(setup, signin, history_contract, terminal_action)
