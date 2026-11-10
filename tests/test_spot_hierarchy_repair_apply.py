"""Exercise the real repair runner against the disposable SQLite fixture."""

import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

from pydantic import SecretStr
import pytest
from sqlalchemy import select, update


@pytest.fixture
def runner(setup, monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "migrations" / "repair_spot_hierarchy_2026_11_10.py"
    spec = importlib.util.spec_from_file_location("isolated_spot_hierarchy_repair_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The runner's database-name guard still executes. The factory is replaced
    # before run(), so this synthetic URL cannot create a MySQL connection.
    settings = SimpleNamespace(database_url=SecretStr(
        "mysql+pymysql://localhost/RIDERLOG_V2_DATA_TEST"))
    monkeypatch.setattr(module, "Settings", lambda: settings)
    monkeypatch.setattr(module, "Database", lambda *_args, **_kwargs: setup["db"])
    monkeypatch.setattr(module, "DeletionStore", lambda _settings: SimpleNamespace(pending=lambda: []))
    monkeypatch.setattr(module, "REFERENCE_COLUMNS", {})
    monkeypatch.setattr(module, "reference_digests", lambda *_args: {"isolated_references": "unchanged"})
    backup_root = tmp_path / "private-repair-backups"
    backup_root.mkdir(mode=0o700)
    monkeypatch.setattr(module, "BACKUP_ROOT", backup_root)
    # Restore the process setting even when a guard intentionally raises.
    original_umask = os.umask(0o077)
    os.umask(original_umask)
    try:
        yield module
    finally:
        os.umask(original_umask)


def _snapshot(setup, runner):
    tables = {name: setup["db"].table(name) for name in runner.TABLES}
    with setup["engine"].connect() as connection:
        return runner.snapshot(connection, tables)


def test_apply_writes_repair_preserves_ids_and_creates_private_recovery_artifacts(setup, runner):
    master = setup["db"].table("MSP_SPOT_MASTER")
    normal_org = setup["db"].table("MSP_ORG")
    with setup["engine"].begin() as connection:
        connection.execute(update(master).where(master.c.spot_master_id == "root").values(
            unit_name="Current synthetic organization"))
        connection.execute(update(normal_org).where(normal_org.c.org_id == "root").values(
            org_name="Stale synthetic organization"))
        connection.execute(update(master).where(master.c.spot_master_id == "child").values(
            unit_name="Current synthetic branch"))
    original = _snapshot(setup, runner)

    runner.run(True)

    repaired = _snapshot(setup, runner)
    assert {row["spot_master_id"] for row in repaired["MSP_SPOT_MASTER"]} == {
        row["spot_master_id"] for row in original["MSP_SPOT_MASTER"]}
    child = next(row for row in repaired["MSP_SPOT_MASTER"] if row["spot_master_id"] == "child")
    assert child["hierarchy_level"] == "region"
    assert child["unit_name"] == child["region_name"] == "Current synthetic branch"
    assert child["spot_name"] is None and child["spot_id"] is None
    assert child["unit_code"] == "CT1-ORG01-R01"
    assert child["region_id"] == "child"
    region = next(row for row in repaired["MSP_REGION"] if row["region_id"] == child["region_id"])
    assert region["region_name"] == "Current synthetic branch"
    old_spot = next(row for row in repaired["MSP_SPOT"] if row["spot_id"] == "child")
    before_spot = next(row for row in original["MSP_SPOT"] if row["spot_id"] == "child")
    assert old_spot == {**before_spot, "is_active": 0}
    assert next(row for row in repaired["MSP_ORG"] if row["org_id"] == "root")["org_name"] == (
        "Current synthetic organization")
    assert repaired["MSP_ADMIN_SPOT_SCOPE"] == original["MSP_ADMIN_SPOT_SCOPE"]
    assert runner.plan_repair(repaired) == ([], [])

    backup_directories = list(runner.BACKUP_ROOT.iterdir())
    assert len(backup_directories) == 1
    backup = backup_directories[0]
    assert stat.S_IMODE(runner.BACKUP_ROOT.stat().st_mode) == 0o700
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert {entry.name for entry in backup.iterdir()} == {
        "before.json", "operations.json", "reference-digests.json", "verified.json"}
    for entry in backup.iterdir():
        assert stat.S_IMODE(entry.stat().st_mode) == 0o600
    archived = json.loads((backup / "before.json").read_text())
    assert set(archived) == set(runner.TABLES)
    assert {row["spot_master_id"] for row in archived["MSP_SPOT_MASTER"]} == {
        row["spot_master_id"] for row in original["MSP_SPOT_MASTER"]}
    verified = json.loads((backup / "verified.json").read_text())
    assert verified["remaining_operations"] == verified["remaining_problems"] == 0
    assert verified["reference_digests_unchanged"] is True


def test_apply_rolls_back_all_hierarchy_tables_when_late_reference_digest_changes(setup, runner, monkeypatch):
    original = _snapshot(setup, runner)
    calls = []

    def changing_references(connection, db):
        table = db.table("MSP_SPOT_MASTER")
        current_level = connection.scalar(select(table.c.hierarchy_level).where(table.c.spot_master_id == "child"))
        calls.append(current_level)
        return {"isolated_references": "before" if len(calls) == 1 else "changed"}

    monkeypatch.setattr(runner, "reference_digests", changing_references)
    with pytest.raises(runner.RepairBlocked, match="Business reference preservation check failed"):
        runner.run(True)

    # Prove the injected failure was after actual mutation, then prove rollback
    # restored every row of all six hierarchy/scope tables.
    assert calls == ["spot", "region"]
    assert _snapshot(setup, runner) == original
    backups = list(runner.BACKUP_ROOT.iterdir())
    assert len(backups) == 1
    assert (backups[0] / "before.json").is_file()
    assert not (backups[0] / "verified.json").exists()


def test_apply_backup_write_failure_aborts_before_any_hierarchy_write(setup, runner, monkeypatch):
    original = _snapshot(setup, runner)
    attempted = []

    def fail_backup(path, _value):
        attempted.append(path.name)
        raise OSError("Injected private backup failure")

    monkeypatch.setattr(runner, "private_json", fail_backup)
    with pytest.raises(OSError, match="Injected private backup failure"):
        runner.run(True)

    assert attempted == ["before.json"]
    assert _snapshot(setup, runner) == original
    assert not list(runner.BACKUP_ROOT.rglob("*.json"))
