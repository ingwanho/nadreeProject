import pytest
from sqlalchemy import select

from app.passport import PassportStorage
from app.rental_schema import metadata


@pytest.mark.parametrize("authenticated", [False, True])
def test_passport_routes_are_not_registered_and_leave_existing_data_untouched(setup, signin, tmp_path, authenticated):
    metadata.create_all(setup["engine"])
    tmp_path = tmp_path / "passport-files"
    tmp_path.mkdir()
    setup["app"].state.passport_storage = PassportStorage(str(tmp_path))
    existing = tmp_path / "existing.jpg"
    existing.write_bytes(b"private existing image")
    users = setup["db"].table("MSP_RENTAL_USER")
    with setup["engine"].begin() as conn:
        conn.execute(users.insert().values(uid_token="passport-owner", passport_img_key="existing.jpg"))
    headers = signin() if authenticated else {}
    for response in (setup["client"].put("/nadreego/rent/passport", headers=headers, json={}),
                     setup["client"].get("/nadreego/rent/passport/BOexisting", headers=headers)):
        assert response.status_code == 404  # Default missing route, not a new API error contract.
    assert existing.read_bytes() == b"private existing image"
    assert len(list(tmp_path.iterdir())) == 1
    with setup["engine"].connect() as conn:
        assert conn.scalar(select(users.c.passport_img_key)) == "existing.jpg"
