"""Move recorded consent timestamps before removing their handover columns."""
from datetime import date, datetime

import pytest
from sqlalchemy import MetaData, Table, inspect, select, text

from app.migrate import apply_operation, migration_plan
from app.rental_schema import metadata

COLS = ("privacy_policy_agreed_at", "terms_agreed_at")


@pytest.fixture
def legacy(setup):
    metadata.create_all(setup["engine"])
    users, reservations = metadata.tables["MSP_RENTAL_USER"], metadata.tables["MSP_RESERVATION"]
    with setup["engine"].begin() as connection:
        for column in COLS:
            connection.execute(text("ALTER TABLE MSP_RENTAL_HANDOVER ADD COLUMN " + column + " DATETIME DEFAULT NULL"))
        for uid in ("consent-one", "consent-two"):
            connection.execute(users.insert().values(uid_token=uid, name="Keep name"))
            connection.execute(reservations.insert().values(reservation_id="r-" + uid, uid_token=uid,
                spot_master_id="root", model_id="legacy-model", start_datetime=datetime(2026, 11, 20),
                end_datetime=datetime(2026, 11, 22), reservation_status="CANCELED"))
    h = Table("MSP_RENTAL_HANDOVER", MetaData(), autoload_with=setup["engine"])
    with setup["engine"].begin() as connection:
        for ident, uid, privacy, terms in [
            ("h-later", "consent-one", datetime(2026, 11, 21), datetime(2026, 11, 22)),
            ("h-earlier", "consent-one", datetime(2026, 11, 20), None),
            ("h-signature-only", "consent-two", None, None),
        ]:
            connection.execute(h.insert().values(handover_id=ident, reservation_id="r-" + uid,
                uid_token=uid, spot_master_id="root", vehicle_id="old-vehicle", final_price=10,
                start_date=date(2026, 11, 20), return_date=date(2026, 11, 22), handover_status="CANCELED",
                signature_status="COMPLETED", signature_completed_at=datetime(2026, 11, 19),
                privacy_policy_agreed_at=privacy, terms_agreed_at=terms))
    return setup


def related(plan):
    return [(label, sql, values) for label, sql, values in plan if any(column in label for column in COLS)]


def apply(ctx, operations):
    for label, sql, values in operations:
        with ctx["engine"].begin() as connection:
            apply_operation(connection, label, sql, values)


def rows(ctx, name, key):
    table = Table(name, MetaData(), autoload_with=ctx["engine"])
    with ctx["engine"].connect() as connection:
        return {row[key]: dict(row) for row in connection.execute(select(table)).mappings()}


def test_upgrade_copies_earliest_actual_consents_before_drop_without_inventing_signature_history(legacy):
    ctx = legacy
    before = rows(ctx, "MSP_RENTAL_HANDOVER", "handover_id")
    with ctx["engine"].begin() as connection:
        for column in COLS:
            connection.execute(text("ALTER TABLE MSP_RENTAL_USER DROP COLUMN " + column))
    operations = related(migration_plan(ctx["db"]))
    assert len(operations) == 6
    assert all(column not in {c["name"] for c in inspect(ctx["engine"]).get_columns("MSP_RENTAL_USER")} for column in COLS)
    assert rows(ctx, "MSP_RENTAL_HANDOVER", "handover_id") == before  # Planning is read-only.
    apply(ctx, operations)
    customers = rows(ctx, "MSP_RENTAL_USER", "uid_token")
    assert customers["consent-one"]["privacy_policy_agreed_at"] == datetime(2026, 11, 20)
    assert customers["consent-one"]["terms_agreed_at"] == datetime(2026, 11, 22)
    assert customers["consent-two"]["privacy_policy_agreed_at"] is customers["consent-two"]["terms_agreed_at"] is None
    assert customers["consent-one"]["name"] == "Keep name"
    after = rows(ctx, "MSP_RENTAL_HANDOVER", "handover_id")
    assert after == {key: {name: value for name, value in row.items() if name not in COLS} for key, row in before.items()}
    assert not related(migration_plan(ctx["db"]))


def test_migration_keeps_the_earliest_timestamp_across_member_and_handover_records(legacy):
    ctx = legacy
    users = metadata.tables["MSP_RENTAL_USER"]
    with ctx["engine"].begin() as connection:
        connection.execute(users.update().where(users.c.uid_token == "consent-one").values(
            privacy_policy_agreed_at=datetime(2026, 11, 18), terms_agreed_at=datetime(2026, 11, 23)))
    apply(ctx, related(migration_plan(ctx["db"])))
    user = rows(ctx, "MSP_RENTAL_USER", "uid_token")["consent-one"]
    assert user["privacy_policy_agreed_at"] == datetime(2026, 11, 18)
    assert user["terms_agreed_at"] == datetime(2026, 11, 22)


def test_drop_guard_preserves_source_if_copy_did_not_complete(legacy):
    ctx = legacy
    operation = next(item for item in related(migration_plan(ctx["db"])) if item[0] ==
        "drop retired MSP_RENTAL_HANDOVER.privacy_policy_agreed_at")
    with pytest.raises(ValueError, match="copy is incomplete"):
        apply(ctx, [operation])
    assert "privacy_policy_agreed_at" in {c["name"] for c in inspect(ctx["engine"]).get_columns("MSP_RENTAL_HANDOVER")}
    assert rows(ctx, "MSP_RENTAL_HANDOVER", "handover_id")["h-earlier"]["privacy_policy_agreed_at"] == datetime(2026, 11, 20)


def test_second_copy_failure_preserves_both_source_columns_and_can_resume(legacy):
    ctx = legacy
    before = rows(ctx, "MSP_RENTAL_HANDOVER", "handover_id")
    with pytest.raises(ValueError, match="simulated second consent copy failure"):
        for operation in related(migration_plan(ctx["db"])):
            if operation[0] == "copy earliest consent to MSP_RENTAL_USER.terms_agreed_at":
                raise ValueError("simulated second consent copy failure")
            apply(ctx, [operation])
    assert set(COLS).issubset({c["name"] for c in inspect(ctx["engine"]).get_columns("MSP_RENTAL_HANDOVER")})
    assert rows(ctx, "MSP_RENTAL_HANDOVER", "handover_id") == before
    member = rows(ctx, "MSP_RENTAL_USER", "uid_token")["consent-one"]
    assert member["privacy_policy_agreed_at"] == datetime(2026, 11, 20)
    assert member["terms_agreed_at"] is None
    apply(ctx, related(migration_plan(ctx["db"])))
    member = rows(ctx, "MSP_RENTAL_USER", "uid_token")["consent-one"]
    assert member["privacy_policy_agreed_at"] == datetime(2026, 11, 20)
    assert member["terms_agreed_at"] == datetime(2026, 11, 22)
    assert not related(migration_plan(ctx["db"]))


def test_interrupted_migration_resumes_after_one_column_was_moved(legacy):
    ctx = legacy
    apply(ctx, [item for item in related(migration_plan(ctx["db"])) if COLS[0] in item[0]])
    pending = related(migration_plan(ctx["db"]))
    assert len(pending) == 2 and all(COLS[1] in item[0] for item in pending)
    apply(ctx, pending)
    assert not related(migration_plan(ctx["db"]))
    assert rows(ctx, "MSP_RENTAL_USER", "uid_token")["consent-one"]["privacy_policy_agreed_at"] == datetime(2026, 11, 20)


def test_orphaned_legacy_consents_block_the_read_only_plan(legacy):
    ctx = legacy
    with ctx["engine"].begin() as connection:
        connection.execute(text("UPDATE MSP_RENTAL_HANDOVER SET uid_token='missing-customer' WHERE handover_id='h-earlier'"))
    with pytest.raises(ValueError, match="no matching customer"):
        migration_plan(ctx["db"])
    assert set(COLS).issubset({c["name"] for c in inspect(ctx["engine"]).get_columns("MSP_RENTAL_HANDOVER")})
