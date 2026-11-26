"""Profile document numbers distinguish omission, replacement, and explicit deletion."""
from cryptography.fernet import Fernet
from pydantic import SecretStr
import pytest

from app.rental_profile import NUMBER_FIELDS
from test_customer_consents import BASE, member, sign_in
from test_nadri_auth import rental_tables


def stored_profile(ctx):
    rental_tables(ctx)
    ctx["settings"].handover_encrypt_key = SecretStr(Fernet.generate_key().decode())
    _, headers = sign_in(ctx, "profile-numbers", privacyPolicyAgreed=True, termsAgreed=True)
    response = ctx["client"].patch(BASE + "/profile", headers=headers, json={
        "passportNumber": "TEST-PASSPORT", "driverLicenseNumber": "TEST-IDP"})
    assert response.status_code == 200, response.text
    return headers, response.json()["user"]


@pytest.mark.parametrize("field", NUMBER_FIELDS)
def test_profile_number_omission_replacement_and_null_deletion(setup, field):
    headers, initial = stored_profile(setup)
    other = next(key for key in NUMBER_FIELDS if key != field)
    before = member(setup, "profile-numbers")
    assert before[NUMBER_FIELDS[field]] != initial[field]
    renamed = setup["client"].patch(BASE + "/profile", headers=headers, json={"NAME": "Updated"})
    assert renamed.status_code == 200
    assert renamed.json()["user"][field] == initial[field]
    assert member(setup, "profile-numbers")[NUMBER_FIELDS[field]] == before[NUMBER_FIELDS[field]]
    replaced = setup["client"].patch(BASE + "/profile", headers=headers, json={field: "TEST-REPLACED"})
    assert replaced.status_code == 200 and replaced.json()["user"][field] == "TEST-REPLACED"
    deleted = setup["client"].patch(BASE + "/profile", headers=headers, json={field: None})
    assert deleted.status_code == 200, deleted.text
    user = deleted.json()["user"]
    assert user[field] is None and user[other] == initial[other]
    after = member(setup, "profile-numbers")
    assert after[NUMBER_FIELDS[field]] is None
    assert after[NUMBER_FIELDS[other]] == before[NUMBER_FIELDS[other]]
    assert user["privacyPolicyAgreedAt"] == initial["privacyPolicyAgreedAt"]
    assert user["termsAgreedAt"] == initial["termsAgreedAt"]
    retried = setup["client"].patch(BASE + "/profile", headers=headers, json={field: None})
    assert retried.status_code == 200 and retried.json()["user"] == user
    viewed = setup["client"].get(BASE + "/profile", headers=headers)
    assert viewed.status_code == 200 and viewed.json()["user"] == user
    login, _ = sign_in(setup, "profile-numbers")
    assert login["user"][field] is None and login["user"][other] == initial[other]


def test_profile_can_clear_both_numbers_and_reject_other_account_targets(setup, signin):
    headers, initial = stored_profile(setup)
    sign_in(setup, "profile-other")
    other_before = member(setup, "profile-other")
    before = member(setup, "profile-numbers")
    body = {"passportNumber": None, "driverLicenseNumber": None}
    assert setup["client"].patch(BASE + "/profile", json=body).status_code == 401
    assert setup["client"].patch(BASE + "/profile", headers=signin(), json=body).status_code == 401
    targeted = setup["client"].patch(BASE + "/profile", headers=headers, json={**body, "UID": "profile-other"})
    assert targeted.status_code == 422
    assert member(setup, "profile-numbers") == before
    deleted = setup["client"].patch(BASE + "/profile", headers=headers, json={**body, "termsAgreed": True})
    assert deleted.status_code == 200, deleted.text
    user = deleted.json()["user"]
    assert user["passportNumber"] is user["driverLicenseNumber"] is None
    assert user["termsAgreedAt"] == initial["termsAgreedAt"]
    assert member(setup, "profile-other") == other_before


@pytest.mark.parametrize("field", ["NAME", "Age", "GENDER", "NATIONALITY", "fcmToken", "snsInfo"])
def test_other_null_fields_do_not_partially_clear_profile_numbers(setup, field):
    headers, _ = stored_profile(setup)
    before = member(setup, "profile-numbers")
    response = setup["client"].patch(BASE + "/profile", headers=headers,
        json={"passportNumber": None, field: None})
    assert response.status_code == 422 and response.json()["errorCode"] == "EMPTY_PROFILE_UPDATE"
    assert member(setup, "profile-numbers") == before


@pytest.mark.parametrize("field", NUMBER_FIELDS)
@pytest.mark.parametrize("value", ["", " ", 123])
def test_invalid_numbers_do_not_partially_clear_other_number(setup, field, value):
    headers, _ = stored_profile(setup)
    before = member(setup, "profile-numbers")
    other = next(key for key in NUMBER_FIELDS if key != field)
    response = setup["client"].patch(BASE + "/profile", headers=headers, json={field: value, other: None})
    assert response.status_code == 422 and response.json()["errorCode"] == "INVALID_INPUT"
    assert member(setup, "profile-numbers") == before
