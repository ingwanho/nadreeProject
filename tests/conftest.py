from datetime import date, timedelta
import os

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, Column, Date, DateTime, Integer, MetaData, Numeric, String, Table, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.security import GENERAL, PRIMARY, now


class TestLimiter:
    def __init__(self):
        self.calls = []

    def check(self, key, limit=10, seconds=60):
        self.calls.append((key, limit, seconds))

    def check_connection(self):
        pass


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("NADREE_") and key != "NADREE_TEST_MYSQL_URL":
            monkeypatch.delenv(key)


def schema(engine):
    metadata = MetaData()
    Table("MSP_ADMIN", metadata,
          Column("admin_id", String(36), primary_key=True), Column("login_id", String(100), unique=True, nullable=False),
          Column("email", String(200)), Column("phone", String(200)), Column("admin_name", String(100)),
          Column("password_hash", String(200), nullable=False), Column("mfa_method", String(10), default="email"),
          Column("account_type", String(30), default="manager"), Column("contract_id", String(20)),
          Column("primary_spot_master_id", String(36)), Column("is_active", Integer, default=1),
          Column("fcm_token", String(512)), Column("fcm_token_updated_at", DateTime), Column("last_login_at", DateTime))
    Table("MSP_ROLE", metadata, Column("role_code", String(30), primary_key=True),
          Column("role_name", String(100), nullable=False), Column("role_desc", Text),
          Column("is_active", Integer, default=1))
    Table("MSP_ADMIN_ROLE", metadata, Column("id", Integer, primary_key=True),
          Column("admin_id", String(36), nullable=False), Column("role_code", String(30), nullable=False),
          Column("assigned_at", DateTime), Column("expires_at", DateTime), UniqueConstraint("admin_id", "role_code"))
    Table("MSP_REFRESH_TOKEN", metadata, Column("token_id", String(36), primary_key=True),
          Column("admin_id", String(36), nullable=False), Column("token_hash", String(200), nullable=False),
          Column("user_agent", String(255)), Column("issued_at", DateTime, nullable=False),
          Column("expires_at", DateTime, nullable=False), Column("revoked_at", DateTime))
    Table("MSP_CONTRACT", metadata, Column("contract_id", String(20), primary_key=True),
          Column("status", String(20), nullable=False), Column("start_date", Date), Column("end_date", Date))
    Table("MSP_SPOT_MASTER", metadata, Column("spot_master_id", String(36), primary_key=True),
          Column("contract_id", String(30), nullable=False), Column("org_id", String(36), nullable=False),
          Column("region_id", String(36)), Column("local_id", String(36)), Column("spot_id", String(36), unique=True),
          Column("org_name", String(100)), Column("region_name", String(100)), Column("local_name", String(100)),
          Column("unit_code", String(60), unique=True, nullable=False), Column("unit_name", String(100)),
          Column("spot_name", String(100), nullable=False), Column("hierarchy_level", String(10)),
          Column("address", String(300)), Column("zip_code", String(20)), Column("biz_reg_num", String(20)),
          Column("phone", String(20)), Column("lat", Numeric(9, 6)), Column("lng", Numeric(9, 6)),
          Column("contract_start", Date), Column("contract_end", Date), Column("is_active", Integer, default=1))
    Table("MSP_SPOT_RENT", metadata, Column("spot_master_id", String(36), primary_key=True),
          Column("legacy_spot_code", String(21), unique=True), Column("invite_code", String(64), unique=True),
          Column("delivery_service_type", String(30), default="NONE"), Column("created_at", DateTime), Column("updated_at", DateTime),
          Column("introduction", String(500)), Column("contact_email", String(200)))
    Table("MSP_ADMIN_SPOT_SCOPE", metadata, Column("id", Integer, primary_key=True),
          Column("admin_id", String(36), nullable=False), Column("spot_master_id", String(36)),
          Column("spot_id", String(36)), Column("unit_code", String(60)), Column("access_type", String(20), default="manage"),
          Column("granted_at", DateTime), Column("granted_by", String(36)),
          UniqueConstraint("admin_id", "spot_master_id", "access_type"))
    Table("MSP_RENTAL_ADMIN_REQUEST", metadata, Column("request_id", String(36), primary_key=True),
          Column("spot_master_id", String(36), nullable=False), Column("admin_id", String(36), nullable=False),
          Column("email", String(200), nullable=False), Column("status", String(20), nullable=False, server_default="REQUESTED"),
          Column("requested_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")), Column("reviewed_at", DateTime),
          Column("reviewed_by_admin_id", String(36)), UniqueConstraint("spot_master_id", "email"),
          UniqueConstraint("spot_master_id", "admin_id"),
          CheckConstraint("status IN ('REQUESTED', 'APPROVED', 'REJECTED')"),
          CheckConstraint("(status = 'REQUESTED' AND reviewed_at IS NULL AND reviewed_by_admin_id IS NULL) OR "
                          "(status IN ('APPROVED', 'REJECTED') AND reviewed_at IS NOT NULL AND reviewed_by_admin_id IS NOT NULL)"))
    for level in ["org", "region", "local", "spot"]:
        columns = [Column(level + "_id", String(36), primary_key=True),
                   Column(level + "_name", String(100), nullable=False), Column("contract_id", String(20), nullable=False),
                   Column("unit_code", String(60), nullable=False, unique=True)]
        for ancestor in ["org", "region", "local"][:["org", "region", "local", "spot"].index(level)]:
            columns.append(Column(ancestor + "_id", String(36), nullable=ancestor != "org"))
        columns.extend([Column("address", String(300)), Column("phone", String(20)), Column("biz_reg_num", String(20)),
                        Column("zip_code", String(10)), Column("lat", Numeric(9, 6)), Column("lng", Numeric(9, 6)),
                        Column("contract_start", Date), Column("contract_end", Date), Column("is_active", Integer, default=1)])
        Table("MSP_" + level.upper(), metadata, *columns)
    metadata.create_all(engine)
    return metadata


@pytest.fixture
def setup(tmp_path, request):
    mysql = bool(request.node.get_closest_marker("mysql"))
    if mysql:
        url = os.environ.get("NADREE_TEST_MYSQL_URL", "")
        if not url:
            pytest.skip("Set NADREE_TEST_MYSQL_URL to an empty disposable nadree_w02_test_* database")
        parsed = make_url(url)
        if parsed.get_backend_name() != "mysql" or not (parsed.database or "").startswith("nadree_w02_test_"):
            pytest.fail("Refusing a database not explicitly named nadree_w02_test_*")
        engine = create_engine(url, isolation_level="READ COMMITTED", pool_pre_ping=True, hide_parameters=True)
        if inspect(engine).get_table_names():
            engine.dispose()
            pytest.fail("Refusing to modify a nonempty MySQL test database")
    else:
        engine = create_engine("sqlite:///" + str(tmp_path / "isolated.db"), connect_args={"check_same_thread": False})
    metadata = schema(engine)
    db = Database(engine=engine)
    for name in metadata.tables:
        db.table(name)
    settings = Settings(_env_file=None, env="test", jwt_secret="isolated-test-key-not-for-deployment-123456789")
    hashed = bcrypt.hashpw(b"Test-password-123!", bcrypt.gensalt(rounds=4)).decode()
    with engine.begin() as conn:
        conn.execute(metadata.tables["MSP_CONTRACT"].insert(), [
            {"contract_id": "CT1", "status": "active"}, {"contract_id": "CT2", "status": "active"}])
        for ident, code, contract in [("root", "CT1-ORG01", "CT1"), ("child", "CT1-ORG01-SP01", "CT1"),
                                      ("sibling", "CT1-ORG010", "CT1"), ("foreign", "CT2-ORG01", "CT2")]:
            level = "spot" if ident == "child" else "org"
            values = {"spot_master_id": ident, "contract_id": contract, "org_id": "root" if ident == "child" else ident,
                      "spot_id": ident if level == "spot" else None, "unit_code": code, "spot_name": ident,
                      "unit_name": ident, "org_name": "root" if ident == "child" else ident, "hierarchy_level": level,
                      "contract_start": date.today() - timedelta(days=365), "contract_end": date.today() + timedelta(days=365)}
            conn.execute(metadata.tables["MSP_SPOT_MASTER"].insert(), values)
            conn.execute(metadata.tables["MSP_SPOT_RENT"].insert(), {"spot_master_id": ident, "invite_code": "invite-" + ident})
            normal = {"contract_id": contract, "unit_code": code, level + "_id": ident, level + "_name": ident}
            if level == "spot":
                normal["org_id"] = "root"
            conn.execute(metadata.tables["MSP_" + level.upper()].insert(), normal)
        conn.execute(metadata.tables["MSP_ROLE"].insert(), [
            {"role_code": code, "role_name": code} for code in [PRIMARY, GENERAL, "viewer"]])
        for ident, root, role in [("primary", "root", PRIMARY), ("general", "root", GENERAL),
                                  ("general2", "root", GENERAL), ("outsider", "foreign", PRIMARY)]:
            conn.execute(metadata.tables["MSP_ADMIN"].insert(), {"admin_id": ident, "login_id": ident + "@example.com",
                "email": ident + "@example.com", "admin_name": ident, "password_hash": hashed, "mfa_method": "none",
                "primary_spot_master_id": root, "contract_id": "CT2" if ident == "outsider" else "CT1"})
            conn.execute(metadata.tables["MSP_ADMIN_ROLE"].insert(), {"admin_id": ident, "role_code": role, "assigned_at": now()})
            conn.execute(metadata.tables["MSP_ADMIN_SPOT_SCOPE"].insert(), {"admin_id": ident, "spot_master_id": root})
    limiter = TestLimiter()
    app = create_app(settings, db, limiter)
    try:
        with TestClient(app) as client:
            yield {"client": client, "db": db, "engine": engine, "settings": settings, "limiter": limiter, "app": app}
    finally:
        if mysql:
            metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(setup):
    return setup["client"]


@pytest.fixture
def applicant(setup):
    def create(ident="applicant", spot="root", **account_values):
        table = setup["db"].table("MSP_ADMIN")
        with setup["engine"].begin() as conn:
            conn.execute(table.insert().values(admin_id=ident, login_id=ident + "@example.com",
                email=ident + "@example.com", admin_name=ident, mfa_method="none",
                password_hash=bcrypt.hashpw(b"Test-password-123!", bcrypt.gensalt(rounds=4)).decode(),
                **{"is_active": 1, "account_type": "manager", **account_values}))
            conn.execute(setup["db"].table("MSP_RENTAL_ADMIN_REQUEST").insert().values(
                request_id=ident + "-request", spot_master_id=spot, admin_id=ident, email=ident + "@example.com"))
        return ident + "@example.com"
    return create


@pytest.fixture
def signin(client):
    def perform(admin="primary", **kwargs):
        response = client.post("/nadreego/admin/login", json={"email": admin + "@example.com", "password": "Test-password-123!", **kwargs})
        assert response.status_code == 200, response.text
        data = response.json()
        return {"Authorization": "Bearer " + data["accessToken"], "X-Refresh-Token": data["refreshToken"]}
    return perform
