import pytest
from sqlalchemy import VARCHAR, delete, inspect, text, update
from sqlalchemy.dialects import mysql

from app.errors import Problem
from app.migrate import migration_plan
from app.schema_check import check_schema
from app.security import GENERAL, PRIMARY


def test_schema_reports_known_unmapped_features(setup):
    with setup["engine"].connect() as conn:
        limitations = check_schema(setup["db"], conn)
    assert "ADMIN_REQUEST_STORAGE_NOT_CONFIGURED" not in limitations
    assert "PHONE_STORAGE_MAPPING_REQUIRED" not in limitations
    assert "SHOP_PROFILE_MAPPING_REQUIRED" not in limitations
    assert limitations == ["MFA_FLOW_NOT_IMPLEMENTED"]


def test_schema_requires_active_rental_roles(setup):
    table = setup["db"].table("MSP_ROLE")
    with setup["engine"].begin() as conn:
        conn.execute(update(table).where(table.c.role_code == PRIMARY).values(is_active=0))
    with setup["engine"].connect() as conn, pytest.raises(Problem) as error:
        check_schema(setup["db"], conn)
    assert error.value.code == "RENTAL_ROLE_NOT_CONFIGURED"


def test_migration_plan_is_read_only_and_idempotent_after_expected_changes(setup):
    plan = migration_plan(setup["db"])
    assert [label for label, sql, params in plan] == ["index MSP_ADMIN.fcm_token"]
    with setup["engine"].begin() as conn:
        conn.execute(text("CREATE INDEX idx_admin_fcm_token ON MSP_ADMIN (fcm_token)"))
    assert migration_plan(setup["db"]) == []


def test_missing_role_has_seed_plan_but_is_not_written(setup):
    roles = setup["db"].table("MSP_ROLE")
    with setup["engine"].begin() as conn:
        conn.execute(delete(roles).where(roles.c.role_code == GENERAL))
    plan = migration_plan(setup["db"])
    assert any(label == "seed role " + GENERAL for label, sql, params in plan)
    assert any(label == "seed role " + GENERAL for label, sql, params in migration_plan(setup["db"]))


def test_missing_request_table_has_read_only_creation_plan(setup):
    table = setup["db"].table("MSP_RENTAL_ADMIN_REQUEST")
    table.drop(setup["engine"])
    plan = migration_plan(setup["db"])
    statements = [sql for label, sql, params in plan if label.startswith("create MSP_RENTAL_ADMIN_REQUEST")]
    assert len(statements) == 1 and "uq_rental_admin_request_email" in statements[0]
    assert "MSP_RENTAL_ADMIN_REQUEST" not in inspect(setup["engine"]).get_table_names()


def test_existing_rental_user_gets_refresh_token_table_plan(setup):
    with setup["engine"].begin() as connection:
        connection.execute(text("""
            CREATE TABLE MSP_RENTAL_USER (
                uid_token VARCHAR(36) PRIMARY KEY,
                fcm_token VARCHAR(512),
                fcm_token_updated_at DATETIME
            )
        """))
    plan = migration_plan(setup["db"])
    labels = {label for label, _, _ in plan}
    assert "add MSP_RENTAL_USER.user_access_revoked_at" in labels
    assert "create MSP_RENTAL_USER_REFRESH_TOKEN (nadri user sessions)" in labels


def test_request_uniqueness_required_in_migration_preflight(setup, monkeypatch):
    from app import migrate
    inspector = inspect(setup["engine"])
    original = inspector.get_unique_constraints
    monkeypatch.setattr(inspector, "get_unique_constraints", lambda name: [] if name == "MSP_RENTAL_ADMIN_REQUEST" else original(name))
    monkeypatch.setattr(migrate, "inspect", lambda engine: inspector)
    with pytest.raises(ValueError, match="request uniqueness"):
        migration_plan(setup["db"])


def reflected_columns(setup, monkeypatch, transform):
    from app import migrate
    inspector = inspect(setup["engine"])
    original = inspector.get_columns
    monkeypatch.setattr(inspector, "get_columns", lambda name: transform(name, original(name)))
    monkeypatch.setattr(migrate, "inspect", lambda engine: inspector)


@pytest.mark.parametrize("existing", [[], ["introduction"], ["contact_email"]])
def test_profile_migration_only_adds_missing_columns(setup, monkeypatch, existing):
    profile = {"introduction", "contact_email"}
    reflected_columns(setup, monkeypatch, lambda name, columns:
        [column for column in columns if column["name"] not in profile - set(existing)] if name == "MSP_SPOT_RENT" else columns)
    plan = migration_plan(setup["db"])
    labels = {label for label, _, _ in plan}
    assert labels == {"index MSP_ADMIN.fcm_token"} | {"add MSP_SPOT_RENT." + name for name in profile - set(existing)}
    assert "introduction" in setup["db"].table("MSP_SPOT_RENT").c


def test_new_spot_table_plan_includes_profile_columns(setup):
    setup["db"].table("MSP_SPOT_RENT").drop(setup["engine"])
    plan = migration_plan(setup["db"])
    labels = [label for label, _, _ in plan]
    creation = next(i for i, label in enumerate(labels) if label.startswith("create MSP_SPOT_RENT"))
    assert labels[creation + 1:creation + 3] == ["add MSP_SPOT_RENT.introduction", "add MSP_SPOT_RENT.contact_email"]
    assert "MSP_SPOT_RENT" not in inspect(setup["engine"]).get_table_names()


@pytest.mark.parametrize("nullable", [True, False])
def test_phone_expansion_preserves_attributes_and_is_read_only(setup, monkeypatch, nullable):
    def previous(name, columns):
        return [{**column, "type": mysql.VARCHAR(20, charset="utf8mb4", collation="utf8mb4_bin"),
                 "nullable": nullable, "comment": "Account's phone", "default": None}
                if name == "MSP_ADMIN" and column["name"] == "phone" else column for column in columns]
    reflected_columns(setup, monkeypatch, previous)
    sql = next(sql for label, sql, params in migration_plan(setup["db"]) if label.startswith("expand MSP_ADMIN.phone"))
    assert "VARCHAR(200)" in sql and "CHARACTER SET utf8mb4" in sql and "COLLATE utf8mb4_bin" in sql
    assert "Account''s phone" in sql
    assert ("NOT NULL" in sql) == (not nullable)
    assert any(label.startswith("expand MSP_ADMIN.phone") for label, _, _ in migration_plan(setup["db"]))


@pytest.mark.parametrize("length", [200, 255])
def test_phone_migration_does_not_shrink_existing_column(setup, monkeypatch, length):
    reflected_columns(setup, monkeypatch, lambda name, columns: [
        {**column, "type": VARCHAR(length)} if name == "MSP_ADMIN" and column["name"] == "phone" else column
        for column in columns])
    assert not any(label.startswith("expand MSP_ADMIN.phone") for label, _, _ in migration_plan(setup["db"]))


def test_phone_custom_default_requires_review(setup, monkeypatch):
    reflected_columns(setup, monkeypatch, lambda name, columns: [
        {**column, "type": VARCHAR(20), "default": "'custom'"} if name == "MSP_ADMIN" and column["name"] == "phone" else column
        for column in columns])
    with pytest.raises(ValueError, match="custom storage/default"):
        migration_plan(setup["db"])


def test_incompatible_existing_profile_column_requires_review(setup, monkeypatch):
    reflected_columns(setup, monkeypatch, lambda name, columns: [
        {**column, "type": VARCHAR(30)} if name == "MSP_SPOT_RENT" and column["name"] == "introduction" else column
        for column in columns])
    with pytest.raises(ValueError, match="introduction has an incompatible"):
        migration_plan(setup["db"])
