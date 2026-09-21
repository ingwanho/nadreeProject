from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from redis import RedisError

from app.config import Settings
from app.errors import Problem
from app.main import create_app
from app.security import RateLimiter, business_today


def test_unconfigured_app_starts_but_cannot_access_database():
    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        response = client.post("/nadreego/admin/login", json={"email": "x", "password": "private"})
        assert response.status_code == 503 and "private" not in response.text
        assert response.headers["Cache-Control"] == "no-store"


def test_production_has_no_secret_fallback():
    with pytest.raises(RuntimeError):
        create_app(Settings(_env_file=None, env="production"))
    with pytest.raises(ValidationError):
        Settings(_env_file=None, access_minutes=0)


def test_business_date_uses_bali_midnight(monkeypatch):
    class Clock:
        @classmethod
        def now(cls, tz):
            return datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("app.security.datetime", Clock)
    assert business_today(Settings(_env_file=None)).isoformat() == "2026-09-15"


def test_limiter_fails_closed_and_uses_hashed_keys():
    limiter = RateLimiter("")
    with pytest.raises(Problem) as error:
        limiter.check("secret-email")
    assert error.value.code == "RATE_LIMIT_NOT_CONFIGURED"

    class RedisClient:
        def eval(self, script, count, key, seconds):
            assert "secret-email" not in key
            return 11

    limiter.redis = RedisClient()
    with pytest.raises(Problem) as error:
        limiter.check("secret-email")
    assert error.value.code == "RATE_LIMITED"

    class FailedRedis:
        def eval(self, *args):
            raise RedisError("private connection details")

    limiter.redis = FailedRedis()
    with pytest.raises(Problem) as error:
        limiter.check("secret-email")
    assert error.value.code == "RATE_LIMIT_UNAVAILABLE"


def test_openapi_has_exact_work_group_routes(client):
    docs = client.get("/docs")
    redoc = client.get("/redoc")
    assert docs.status_code == 200 and "swagger-ui" in docs.text
    assert redoc.status_code == 200 and "redoc" in redoc.text.lower()
    paths = client.get("/openapi.json").json()["paths"]
    assert len([path for path in paths if not path.startswith("/health/")]) == 48
    assert "/nadreego/admin/signup" in paths
    assert "/api/v1/nadri/rental/request/cancel" in paths
    for path in ("/api/v1/nadri/user/login", "/api/v1/nadri/user/profile", "/api/v1/nadri/rental/availability",
                 "/api/v1/nadri/rental/request", "/api/v1/nadri/rental/payment/order",
                 "/api/v1/nadri/rental/payment/capture", "/api/v1/nadri/rental/ongoing",
                 "/api/v1/nadri/rental/completed", "/api/v1/nadri/user/refresh", "/api/v1/nadri/user/logout"):
        assert path in paths
    assert "/nadreego/admin/refresh" in paths
    assert "get" in paths["/nadreego/admin/refresh"]
    assert "post" in paths["/nadreego/admin/fcmToken"]
