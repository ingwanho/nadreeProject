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
    openapi = client.get("/openapi.json").json()
    paths = openapi["paths"]
    assert len([path for path in paths if not path.startswith("/health/")]) == 51
    assert "/nadreego/admin/signup" in paths
    assert "/api/v1/nadree/rental/request/cancel" in paths
    for path in ("/api/v1/nadree/user/login", "/api/v1/nadree/user/profile", "/api/v1/nadree/rental/availability",
                 "/api/v1/nadree/rental/request", "/api/v1/nadree/rental/payment/order",
                 "/api/v1/nadree/rental/payment/capture", "/api/v1/nadree/rental/payment/{paymentId}",
                 "/api/v1/nadree/rental/ongoing",
                 "/api/v1/nadree/rental/completed", "/api/v1/nadree/user/refresh", "/api/v1/nadree/user/logout",
                 "/nadreego/rent/passport", "/nadreego/rent/passport/{booked_no}"):
        assert path in paths
    assert "/nadreego/admin/refresh" in paths
    assert "get" in paths["/nadreego/admin/refresh"]
    assert "post" in paths["/nadreego/admin/fcmToken"]
    passport_request = paths["/nadreego/rent/passport"]["put"]["requestBody"]["content"]["application/json"]
    assert passport_request["example"]["masked"] is True
    assert passport_request["example"]["contentType"] == "image/jpeg"
    assert paths["/nadreego/rent/passport"]["put"]["responses"]["200"]["content"]["application/json"]["example"]["available"] is True
    passport_response = paths["/nadreego/rent/passport/{booked_no}"]["get"]["responses"]["200"]["content"]
    assert passport_response["image/jpeg"]["schema"] == {"type": "string", "format": "binary"}
    assert passport_response["image/png"]["schema"] == {"type": "string", "format": "binary"}


def test_configured_cors_allows_web_origin():
    origin = "https://www.riderlog-lte.com:50045"
    app = create_app(Settings(_env_file=None, cors_origins=origin))
    with TestClient(app) as configured_client:
        headers = {"Origin": origin}
        response = configured_client.get("/health/live", headers=headers)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin

        preflight = configured_client.options(
            "/api/v1/nadree/rental/request",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == origin
        assert "authorization" in preflight.headers["access-control-allow-headers"].lower()
