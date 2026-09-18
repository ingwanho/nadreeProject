import argparse
from pathlib import Path

from sqlalchemy import Column, VARCHAR, inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateColumn

from app.config import Settings
from app.db import Database
from app.errors import Problem
from app.schema_check import REQUIRED
from app.security import GENERAL, PRIMARY


def migration_plan(db):
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    planned_tables = {"MSP_SPOT_RENT": "001_spot_rent.sql", "MSP_RENTAL_ADMIN_REQUEST": "002_rental_admin_request.sql"}
    spot_profile = {"introduction": 500, "contact_email": 200}
    missing_tables = set(REQUIRED) - set(planned_tables) - tables
    if missing_tables:
        raise ValueError("Existing service tables missing: " + ", ".join(sorted(missing_tables)))
    operations = []
    for name, required in REQUIRED.items():
        if name in planned_tables and name not in tables:
            sql = (Path(__file__).resolve().parent.parent / "migrations" / planned_tables[name]).read_text()
            operations.append(("create " + name + " (approved DB plan v2.24)", sql, {}))
            if name == "MSP_SPOT_RENT":
                for column, length in spot_profile.items():
                    operations.append(("add MSP_SPOT_RENT." + column,
                        f"ALTER TABLE MSP_SPOT_RENT ADD COLUMN {column} VARCHAR({length}) DEFAULT NULL", {}))
            continue
        columns = {row["name"]: row for row in inspector.get_columns(name)}
        missing = set(required.split()) - set(columns)
        if name == "MSP_ADMIN":
            for column, kind in [("fcm_token", "VARCHAR(512)"), ("fcm_token_updated_at", "DATETIME")]:
                if column in missing:
                    operations.append(("add MSP_ADMIN." + column,
                        f"ALTER TABLE MSP_ADMIN ADD COLUMN {column} {kind} DEFAULT NULL", {}))
                    missing.remove(column)
            if "fcm_token" in columns and getattr(columns["fcm_token"]["type"], "length", 0) < 512:
                raise ValueError("MSP_ADMIN.fcm_token has an incompatible type/length; manual review required")
            if "phone" in columns:
                phone = columns["phone"]
                if not isinstance(phone["type"], VARCHAR) or not phone["type"].length:
                    raise ValueError("MSP_ADMIN.phone is not VARCHAR; manual review required")
                if phone["type"].length < 200:
                    if phone.get("computed") or phone.get("default") not in (None, "NULL"):
                        raise ValueError("MSP_ADMIN.phone has custom storage/default; manual review required")
                    # Preserve reflected charset, collation, nullability and comment when widening.
                    kind = phone["type"].copy()
                    kind.length = 200
                    definition = CreateColumn(Column("phone", kind, nullable=phone["nullable"],
                        server_default=text("NULL") if phone["nullable"] else None, comment=phone.get("comment")))
                    operations.append(("expand MSP_ADMIN.phone to VARCHAR(200)",
                        "ALTER TABLE MSP_ADMIN MODIFY COLUMN " + str(definition.compile(dialect=mysql.dialect())), {}))
        if name == "MSP_SPOT_RENT":
            for column, length in spot_profile.items():
                if column in missing:
                    operations.append(("add MSP_SPOT_RENT." + column,
                        f"ALTER TABLE MSP_SPOT_RENT ADD COLUMN {column} VARCHAR({length}) DEFAULT NULL", {}))
                    missing.remove(column)
                elif not isinstance(columns[column]["type"], VARCHAR) or (columns[column]["type"].length or 0) < length:
                    raise ValueError("MSP_SPOT_RENT." + column + " has an incompatible type/length; manual review required")
        if missing:
            raise ValueError(name + " missing existing columns: " + ", ".join(sorted(missing)))
        if name == "MSP_RENTAL_ADMIN_REQUEST":
            unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)}
            unique.update(tuple(item["column_names"]) for item in inspector.get_indexes(name) if item["unique"])
            if not {("spot_master_id", "email"), ("spot_master_id", "admin_id")}.issubset(unique):
                raise ValueError(name + " missing request uniqueness constraints; manual review required")
    if "MSP_RENTAL_PAYMENT" in tables:
        columns = {row["name"] for row in inspector.get_columns("MSP_RENTAL_PAYMENT")}
        payment_columns = [
            ("refund_status", "VARCHAR(20) NOT NULL DEFAULT 'NONE'"),
            ("paypal_refund_id", "VARCHAR(50) DEFAULT NULL"),
            ("refund_requested_at", "DATETIME DEFAULT NULL"),
            ("refund_requested_by_admin_id", "VARCHAR(36) DEFAULT NULL"),
            ("refund_reason", "VARCHAR(200) DEFAULT NULL"),
        ]
        for column, definition in payment_columns:
            if column not in columns:
                operations.append(("add MSP_RENTAL_PAYMENT." + column,
                    "ALTER TABLE MSP_RENTAL_PAYMENT ADD COLUMN " + column + " " + definition, {}))
        indexes = {tuple(item["column_names"]) for item in inspector.get_indexes("MSP_RENTAL_PAYMENT")}
        if ("refund_status", "updated_at") not in indexes:
            operations.append(("index MSP_RENTAL_PAYMENT.refund_status",
                "CREATE INDEX idx_rental_payment_refund ON MSP_RENTAL_PAYMENT (refund_status, updated_at)", {}))
        checks = {item.get("name") for item in inspector.get_check_constraints("MSP_RENTAL_PAYMENT")}
        if "ck_refund_status" not in checks:
            operations.append(("constraint MSP_RENTAL_PAYMENT.refund_status",
                "ALTER TABLE MSP_RENTAL_PAYMENT ADD CONSTRAINT ck_refund_status CHECK "
                "(refund_status IN ('NONE','NOT_REQUIRED','REQUESTED','PENDING','COMPLETED','FAILED'))", {}))
    if "MSP_RENTAL_USER" in tables:
        user_columns = {row["name"] for row in inspector.get_columns("MSP_RENTAL_USER")}
        if "user_access_revoked_at" not in user_columns:
            operations.append(("add MSP_RENTAL_USER.user_access_revoked_at",
                "ALTER TABLE MSP_RENTAL_USER ADD COLUMN user_access_revoked_at DATETIME DEFAULT NULL", {}))
        if "MSP_RENTAL_USER_REFRESH_TOKEN" not in tables:
            sql = (Path(__file__).resolve().parent.parent / "migrations" / "008_rental_user_refresh_token.sql").read_text()
            operations.append(("create MSP_RENTAL_USER_REFRESH_TOKEN (nadri user sessions)", sql, {}))

    indexes = inspector.get_indexes("MSP_ADMIN")
    if not any(index["column_names"] == ["fcm_token"] for index in indexes):
        if any(index["name"] == "idx_admin_fcm_token" for index in indexes):
            raise ValueError("idx_admin_fcm_token has an incompatible definition")
        operations.append(("index MSP_ADMIN.fcm_token", "CREATE INDEX idx_admin_fcm_token ON MSP_ADMIN (fcm_token)", {}))
    role_table = db.table("MSP_ROLE")
    with db.engine.connect() as conn:
        rows = {row["role_code"]: row for row in conn.execute(select(role_table)).mappings()}
    for code, title in [(PRIMARY, "Rental primary admin"), (GENERAL, "Rental manager")]:
        if code not in rows:
            operations.append(("seed role " + code,
                "INSERT INTO MSP_ROLE (role_code, role_name, is_active) VALUES (:code, :name, 1)", {"code": code, "name": title}))
        elif not rows[code]["is_active"]:
            raise ValueError("Role is disabled; manual approval required: " + code)
    return operations


def main():
    parser = argparse.ArgumentParser(description="W00-W02 shared MySQL migration. Read-only plan by default.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database", default="")
    args = parser.parse_args()
    settings = Settings()
    db = Database(settings.database_url.get_secret_value())
    if db.engine is None or db.engine.dialect.name != "mysql":
        parser.exit(2, "NADREE_DATABASE_URL must explicitly identify a MySQL database.\n")
    if args.apply and args.confirm_database != db.engine.url.database:
        parser.exit(2, "--apply requires --confirm-database matching the configured database name.\n")
    try:
        # Single migration owner, including plan recomputation under the connection lock.
        with db.engine.connect() as guard:
            if args.apply and guard.scalar(text("SELECT GET_LOCK('nadree:w00-w02:migration', 0)")) != 1:
                raise ValueError("Another Nadree migration is running")
            try:
                operations = migration_plan(db)
                for label, sql, parameters in operations:
                    print(("APPLY " if args.apply else "PENDING ") + label)
                    if args.apply:
                        with db.engine.begin() as conn:
                            conn.execute(text(sql), parameters)
                print("No pending changes." if not operations else "Applied." if args.apply else "Read-only plan; no database writes.")
            finally:
                if args.apply:
                    guard.execute(text("SELECT RELEASE_LOCK('nadree:w00-w02:migration')"))
    except ValueError as error:
        parser.exit(2, str(error) + "\n")
    except (SQLAlchemyError, Problem):
        parser.exit(2, "Database operation failed; credentials/SQL parameters withheld. Recheck the schema before retrying.\n")
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    main()
