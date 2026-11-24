"""Initialize only an unused handover key, without displaying any secrets.

Run as the .env owner from /srv/nadree-api after app.migrate. No key rotation.
"""
import argparse
import fcntl
from io import StringIO
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.fernet import Fernet
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, select, MetaData, Table
from sqlalchemy.engine import make_url

from app.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-database", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    url = make_url(settings.database_url.get_secret_value())
    if not url.database or url.database != args.confirm_database:
        parser.error("Database confirmation does not match configured target")
    path = Path(".env")
    if path.is_symlink() or path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o077:
        parser.error("Run as the owner of the regular private .env (mode 600)")
    with path.open("r+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        original = stream.read()
        configured = settings.handover_encrypt_key.get_secret_value()
        stored = dotenv_values(stream=StringIO(original)).get("NADREE_HANDOVER_ENCRYPT_KEY") or ""
        if configured != stored:
            parser.error("Environment override differs from .env; resolve it without rotating keys")
        try:
            key = Fernet(configured.encode()) if configured else None
        except (ValueError, TypeError):
            parser.error("Existing handover key is invalid; restore it, never replace it automatically")
        engine = create_engine(url)
        count = 0
        try:
            with engine.connect() as connection:
                inspector = inspect(connection)
                for name, columns in {
                    "MSP_RENTAL_USER": ("passport_number_enc", "driver_license_number_enc"),
                    "MSP_RENTAL_HANDOVER": ("passport_number_enc", "driver_license_number_enc",
                        "accommodation_location_enc", "sns_snapshot_enc", "pending_changes_enc"),
                }.items():
                    if not inspector.has_table(name):
                        continue
                    table = Table(name, MetaData(), autoload_with=connection)
                    for column in columns:
                        if column not in table.c:
                            continue
                        values = connection.scalars(select(table.c[column]).where(table.c[column].is_not(None)))
                        for value in values:
                            if not value:
                                continue
                            count += 1
                            if key:
                                try:
                                    key.decrypt(value.encode())
                                except Exception:
                                    parser.error("Stored handover ciphertext does not match configured key; restore the original key")
        finally:
            engine.dispose()
        if configured:
            print("Existing handover key retained; encrypted fields checked. No writes.")
            return
        if count:
            parser.error("Private handover/profile data already exists; restore its key before continuing")
        if not args.apply:
            print("No private handover ciphertext; initialization is eligible. Read-only, no writes.")
            return
        directory = Path.home() / ".nadree-private"
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_uid != os.geteuid() or directory.stat().st_mode & 0o077:
            parser.error("Private backup directory must be owned by this user with mode 700")
        backup = directory / ("env-before-handover-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as target:
            target.write(original)
        content = re.sub(r"(?m)^[ \t]*(?:export[ \t]+)?NADREE_HANDOVER_ENCRYPT_KEY[ \t]*=.*(?:\n|$)", "", original)
        content = content.rstrip("\n") + "\nNADREE_HANDOVER_ENCRYPT_KEY='" + Fernet.generate_key().decode() + "'\n"
        stream.seek(0)
        stream.write(content)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
        print("Handover key initialized privately. Existing phone key preserved. Private .env backup created.")


if __name__ == "__main__":
    main()
