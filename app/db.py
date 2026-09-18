from threading import RLock

from fastapi import Request
from sqlalchemy import MetaData, Table, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.errors import Problem


class Database:
    def __init__(self, url: str = "", engine=None):
        options = {"isolation_level": "READ COMMITTED"} if url and make_url(url).get_backend_name() == "mysql" else {}
        self.engine = engine or (create_engine(url, pool_pre_ping=True, hide_parameters=True, **options) if url else None)
        self.metadata = MetaData()
        self.lock = RLock()
        if self.engine is not None and self.engine.dialect.name == "mysql":
            @event.listens_for(self.engine, "connect")
            def utc_session(dbapi_connection, _):
                with dbapi_connection.cursor() as cursor:
                    cursor.execute("SET time_zone = '+00:00'")

    def table(self, name):
        if self.engine is None:
            raise Problem(503, "DATABASE_NOT_CONFIGURED")
        with self.lock:
            if name not in self.metadata.tables:
                Table(name, self.metadata, autoload_with=self.engine)
            return self.metadata.tables[name]


def transaction(request: Request):
    db = request.app.state.db
    if db.engine is None:
        raise Problem(503, "DATABASE_NOT_CONFIGURED")
    with db.engine.connect() as connection, Session(connection) as session:
        try:
            read_paths = {"/nadreego/vehicle/select", "/nadreego/brand", "/nadreego/booking/select",
                          "/nadreego/main", "/nadreego/main/calendar", "/nadreego/vehicle/location"}
            consistent_read = request.url.path in read_paths or request.method == "GET" and request.url.path.startswith("/nadreego/shop/")
            if consistent_read and connection.dialect.name == "mysql":
                connection.execution_options(isolation_level="REPEATABLE READ")
            with session.begin():
                yield session
        finally:
            # MySQL named locks belong to the connection, not the transaction.
            for name in session.info.get("named_locks", []):
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})


def lock_email(session, email):
    if session.bind.dialect.name != "mysql":
        return
    from app.security import fingerprint
    name = "nadree:email:" + fingerprint(email.casefold())[:48]
    if session.scalar(text("SELECT GET_LOCK(:name, 3)"), {"name": name}) != 1:
        raise Problem(409, "EMAIL_UPDATE_BUSY")
    session.info.setdefault("named_locks", []).append(name)


def require_columns(table, values):
    for name, value in values.items():
        if name not in table.c:
            raise Problem(503, "SCHEMA_MAPPING_REQUIRED")
        maximum = getattr(table.c[name].type, "length", None)
        if maximum and isinstance(value, str) and len(value) > maximum:
            raise Problem(422, "VALUE_EXCEEDS_DB_LIMIT")
