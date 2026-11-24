"""Deployment key initialization uses only temporary configuration and SQLite."""
import importlib.util
from pathlib import Path
import sys

from cryptography.fernet import Fernet
from dotenv import dotenv_values
import pytest
from sqlalchemy import create_engine, text


@pytest.fixture
def initializer(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "deployment/initialize_handover_key.py"
    spec = importlib.util.spec_from_file_location("handover_key_initializer", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "operator-home"))
    (tmp_path / "operator-home").mkdir()
    monkeypatch.setattr(sys, "argv", [str(source), "--confirm-database", str(tmp_path / "test.db")])
    env = tmp_path / ".env"
    env.write_text("NADREE_DATABASE_URL='sqlite+pysqlite:///" + str(tmp_path / "test.db") + "'\n"
                   "NADREE_FIELD_ENCRYPT_KEY='invalid-legacy-value-must-stay'\nNADREE_HANDOVER_ENCRYPT_KEY=''\n")
    env.chmod(0o600)
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "test.db"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE MSP_RENTAL_USER (passport_number_enc TEXT)"))
    yield module, env, engine
    engine.dispose()


def test_initialization_is_read_only_by_default_and_never_rotates(initializer, monkeypatch, capsys):
    module, env, engine = initializer
    original = env.read_bytes()
    module.main()
    assert env.read_bytes() == original
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--apply"])
    module.main()
    values = dotenv_values(env)
    assert values["NADREE_FIELD_ENCRYPT_KEY"] == "invalid-legacy-value-must-stay"
    key = values["NADREE_HANDOVER_ENCRYPT_KEY"]
    assert Fernet(key.encode())
    after = env.read_bytes()
    module.main()
    assert env.read_bytes() == after
    assert key not in capsys.readouterr().out
    assert list((Path.home() / ".nadree-private").iterdir())[0].read_bytes() == original


def test_ciphertext_blocks_new_key_and_preserves_files(initializer, monkeypatch):
    module, env, engine = initializer
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO MSP_RENTAL_USER VALUES (:value)"),
            {"value": Fernet(Fernet.generate_key()).encrypt(b"old-private-value").decode()})
    original = env.read_bytes()
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--apply"])
    with pytest.raises(SystemExit):
        module.main()
    assert env.read_bytes() == original


def test_invalid_existing_handover_key_is_never_replaced(initializer, monkeypatch):
    module, env, _ = initializer
    env.write_text(env.read_text().replace("NADREE_HANDOVER_ENCRYPT_KEY=''", "NADREE_HANDOVER_ENCRYPT_KEY='invalid-existing-value'"))
    original = env.read_bytes()
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--apply"])
    with pytest.raises(SystemExit):
        module.main()
    assert env.read_bytes() == original
