"""Canonical node names must reach readers even when the leaf name is absent."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from account_deletion_helpers import MemoryDeletionStore, PrivacyChatStore
from app.chat_sync import sync_catalogue
from app.spot_hierarchy import unit_name
from test_pending_reservation_approval import pending_bookings


CURRENT_NAME = "Current organization name"


@pytest.fixture(params=[None, "Stale legacy spot name"], ids=["no-leaf-name", "stale-leaf-name"])
def named_root(setup, pending_bookings, request):
    master = setup["db"].table("MSP_SPOT_MASTER")
    with setup["engine"].begin() as connection:
        connection.execute(update(master).where(master.c.spot_master_id == "root").values(
            unit_name=CURRENT_NAME, spot_name=request.param))
        row = connection.execute(select(master).where(master.c.spot_master_id == "root")).mappings().one()
        assert row["hierarchy_level"] == "org" and row["spot_id"] is None
    return setup


def test_spotcheck_returns_the_nodes_canonical_name(named_root, signin):
    ctx = named_root
    headers = signin()
    rent = ctx["db"].table("MSP_SPOT_RENT")
    with ctx["engine"].connect() as connection:
        invite = connection.scalar(select(rent.c.invite_code).where(rent.c.spot_master_id == "root"))

    response = ctx["client"].post("/nadreego/admin/spotcheck", headers=headers, json={"spotCode": invite})

    assert response.status_code == 200, response.text
    assert response.json()["spotMasterId"] == "root"
    assert response.json()["spotName"] == CURRENT_NAME
    # A display lookup must neither consume the invitation nor change access.
    with ctx["engine"].connect() as connection:
        assert connection.scalar(select(rent.c.invite_code).where(rent.c.spot_master_id == "root")) == invite


def test_dashboard_group_uses_the_nodes_canonical_name(named_root, signin):
    ctx = named_root

    response = ctx["client"].get("/nadreego/main", headers=signin())

    assert response.status_code == 200, response.text
    assert response.json()["group"] == {
        "spotMasterId": "root", "spotCode": "CT1-ORG01", "name": CURRENT_NAME}
    assert response.json()["totalVehicles"] == 3


def test_customer_availability_uses_the_nodes_canonical_name(named_root):
    ctx = named_root
    start = date.today() + timedelta(days=1)

    response = ctx["client"].post("/api/v1/nadree/rental/availability", json={
        "startDate": start.isoformat(), "returnDate": (start + timedelta(days=2)).isoformat(),
        "cc": 125, "deliveryRequested": False})

    assert response.status_code == 200, response.text
    items = [item for item in response.json()["items"] if item["shopId"] == "root"]
    assert len(items) == 1
    assert items[0]["spot"]["spotMasterId"] == "root"
    assert items[0]["spot"]["spotName"] == CURRENT_NAME
    assert items[0]["modelId"] == "pending-model"


def test_privacy_scope_inspection_uses_the_nodes_canonical_name(named_root, signin):
    ctx = named_root
    ctx["app"].state.deletions = MemoryDeletionStore()

    response = ctx["client"].get("/nadreego/admin/account-deletion-context", headers=signin())

    assert response.status_code == 200, response.text
    assert response.json()["directShopName"] == CURRENT_NAME
    assert response.json()["scope"] == "SUBTREE"
    assert response.json()["affectedShopCount"] == 2
    assert response.json()["activeRequestId"] is None
    assert list(ctx["app"].state.deletions.records()) == []


def test_chat_catalogue_uses_the_nodes_canonical_name(named_root):
    ctx = named_root
    store = PrivacyChatStore()
    store.ref("chatShops/root").set({"active": True, "displayName": "Old cached label", "preserved": "existing"})
    chat = SimpleNamespace(settings=ctx["settings"], store=lambda: store)

    sync_catalogue(ctx["db"], chat)

    shop = store.ref("chatShops/root").get().to_dict()
    assert shop["displayName"] == CURRENT_NAME
    assert shop["active"] is True and shop["preserved"] == "existing"
    product = store.ref("chatShops/root/products/pending-model").get().to_dict()
    assert product["active"] is True and product["displayName"] == "Test"


@pytest.mark.parametrize("canonical", [None, ""])
def test_cleared_canonical_name_does_not_revive_a_stale_leaf_name(canonical):
    assert unit_name({"unit_name": canonical, "spot_name": "Stale leaf name"}) == canonical


def test_legacy_row_without_a_canonical_column_keeps_its_existing_name():
    assert unit_name({"spot_name": "Legacy leaf name"}) == "Legacy leaf name"
