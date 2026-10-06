import base64
from datetime import datetime

from sqlalchemy import update

from app.passport import PassportStorage
from app.rental_schema import metadata as rental_metadata
from app.security import now


def test_masked_passport_upload_is_branch_scoped_and_closed_after_return(setup, tmp_path, signin):
    rental_metadata.create_all(setup["engine"])
    setup["app"].state.passport_storage = PassportStorage(str(tmp_path))
    tables = {name: setup["db"].table(name) for name in (
        "MSP_RENTAL_USER", "MSP_RESERVATION", "MSP_RENTAL_CONTRACT")}
    at = datetime(2026, 10, 7, 1, 0)
    with setup["engine"].begin() as connection:
        connection.execute(tables["MSP_RENTAL_USER"].insert().values(uid_token="passport-user"))
        connection.execute(tables["MSP_RESERVATION"].insert().values(
            reservation_id="passport-r1", uid_token="passport-user", spot_master_id="root", model_id="model-1",
            vehicle_assignment_status="LOCKED", start_datetime=at, end_datetime=at,
            reservation_status="HANDED_OVER", created_at=at, updated_at=at))
        connection.execute(tables["MSP_RENTAL_CONTRACT"].insert().values(
            rental_contract_id="passport-c1", reservation_id="passport-r1", vehicle_id="vehicle-1",
            uid_token="passport-user", pickup_spot_master_id="root", actual_start_time=at,
            planned_end_date=at.date(), contract_status="ON_RENT", created_at=at, updated_at=at))

    headers = signin()
    image = base64.b64encode(b"\xff\xd8\xff\xd9").decode()
    uploaded = setup["client"].put("/nadreego/rent/passport", headers=headers, json={
        "bookedNo": "BOpassport-r1", "contentType": "image/jpeg", "imageBase64": image, "masked": True})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["available"] is True
    assert uploaded.json()["downloadPath"] == "/nadreego/rent/passport/BOpassport-r1"

    viewed = setup["client"].get("/nadreego/rent/passport/BOpassport-r1", headers=headers)
    assert viewed.status_code == 200
    assert viewed.headers["cache-control"] == "no-store"
    assert viewed.content == b"\xff\xd8\xff\xd9"

    with setup["engine"].begin() as connection:
        connection.execute(update(tables["MSP_RENTAL_CONTRACT"]).where(
            tables["MSP_RENTAL_CONTRACT"].c.rental_contract_id == "passport-c1").values(
                contract_status="RETURNED", actual_end_time=at))
    expired = setup["client"].get("/nadreego/rent/passport/BOpassport-r1", headers=headers)
    assert expired.status_code == 404


def test_passport_upload_requires_mask_acknowledgement(setup, tmp_path, signin):
    rental_metadata.create_all(setup["engine"])
    setup["app"].state.passport_storage = PassportStorage(str(tmp_path))
    at = now()
    tables = {name: setup["db"].table(name) for name in (
        "MSP_RENTAL_USER", "MSP_RESERVATION", "MSP_RENTAL_CONTRACT")}
    with setup["engine"].begin() as connection:
        connection.execute(tables["MSP_RENTAL_USER"].insert().values(uid_token="passport-user-2"))
        connection.execute(tables["MSP_RENTAL_CONTRACT"].insert().values(
            rental_contract_id="passport-c2", reservation_id=None, vehicle_id="vehicle-2",
            uid_token="passport-user-2", pickup_spot_master_id="root", actual_start_time=at,
            planned_end_date=at.date(), contract_status="ON_RENT", created_at=at, updated_at=at))

    response = setup["client"].put("/nadreego/rent/passport", headers=signin(), json={
        "bookedNo": "RTpassport-c2", "contentType": "image/jpeg",
        "imageBase64": base64.b64encode(b"\xff\xd8\xff\xd9").decode(), "masked": False})
    assert response.status_code == 422
    assert response.json()["errorCode"] == "PASSPORT_MASK_REQUIRED"
