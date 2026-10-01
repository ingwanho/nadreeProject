from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text

from app.auth import router as auth_router
from app.admin_signup import router as admin_signup_router
from app.config import Settings
from app.db import Database
from app.errors import Problem, install_handlers
from app.fcm import FcmSender
from app.firebase_auth import CustomerFirebaseAuth
from app.management import router as management_router
from app.mail import PasswordMailer
from app.locations import VehicleLocations
from app.openapi_examples import (OPENAPI_EXAMPLES, OPENAPI_REQUEST_EXAMPLES,
                                   OPENAPI_RESPONSE_EXAMPLES)
from app.delivery import router as delivery_router
from app.paypal import PayPalClient, router as paypal_router
from app.customer_rentals import router as customer_rentals_router, user_router as customer_users_router
from app.pricing import router as pricing_router
from app.readmodels import router as readmodels_router
from app.rentals import router as rentals_router
from app.vehicles import router as vehicles_router
from app.responses import Error
from app.schema_check import check_schema
from app.security import RateLimiter, sign_access

OPENAPI_TAGS = [
    {"name": "W00 Health", "description": "서비스 상태와 의존성 확인. 테스트 시작 시 `/health/live`와 `/health/ready`를 먼저 확인합니다."},
    {"name": "W01 Accounts", "description": "관리자 로그인·가입 신청·토큰·프로필"},
    {"name": "W02 Organizations and admins", "description": "지점 계층과 관리자 권한"},
    {"name": "W03 Vehicles and QR", "description": "차량·QR·센서 관리"},
    {"name": "W04 Pricing", "description": "차량 가격과 렌탈 티어"},
    {"name": "W05 Delivery", "description": "배송 지역과 배송비"},
    {"name": "W06 Reservations and rentals", "description": "예약·렌트·인계·반납. 테스트 시드 예약은 `NRTEST-RES-*`, 차량은 `NRTEST-VEHICLE-*`입니다."},
    {"name": "W07 Dashboard and calendar", "description": "운영 현황과 캘린더 조회"},
    {"name": "W08 PayPal webhook", "description": "PayPal 결제·환불·웹훅"},
    {"name": "Nadree customer users", "description": "나드리 고객 UID 로그인·프로필·토큰. 로그인에는 Firebase ID Token과 body의 UID가 모두 필요합니다."},
    {"name": "Nadree customer rentals", "description": "나드리 차량 조회·예약·결제·렌트 이력. 테스트 지점은 `00000000-0000-4000-8000-000000000101`, 모델은 `NRTEST-MODEL-125`와 `NRTEST-MODEL-155`입니다."},
]

OPENAPI_DESCRIPTION = """
나드리·나드리고 렌탈 API입니다.

## 문서 사용 순서

1. `/health/live`로 프로세스 상태를 확인합니다.
2. `/health/ready`가 `status=ok`인지 확인합니다.
3. 관리자 API는 `/nadreego`, 고객 API는 `/api/v1/nadree` 경로를 사용합니다.
4. 요청·응답 필드는 각 작업의 Schema를 기준으로 작성합니다.

## 테스트 데이터 표시 규칙

`NRTEST-` 접두사가 붙은 값은 테스트 시드 데이터입니다. 실제 운영 데이터와 섞어 사용하지 않습니다.

- 테스트 지점(`spotMasterId`/`shopId`): `00000000-0000-4000-8000-000000000101`
- 테스트 모델: `NRTEST-MODEL-125`(Honda Vario 125, 125cc), `NRTEST-MODEL-155`(Yamaha NMAX 155, 155cc)
- 테스트 차량: `NRTEST-VEHICLE-301`(대여 가능), `NRTEST-VEHICLE-302`(정비), `NRTEST-VEHICLE-303`(진행 중 렌트), `NRTEST-VEHICLE-304`(미래 승인 예약)
- 예약 상태 샘플: `NRTEST-RES-REQ-001`, `NRTEST-RES-APP-001`, `NRTEST-RES-PENDING-001`, `NRTEST-RES-REJECT-001`, `NRTEST-RES-CANCEL-001`, `NRTEST-RES-EXPIRED-001`, `NRTEST-RES-HAND-001`, `NRTEST-RES-RETURN-001`
- 테스트 통화: `USD`; 테스트 가격 기준: 125cc 일일 25 USD, 155cc 일일 35 USD

테스트 데이터의 전체 실행 순서와 예상 결과는 저장소의 `docs/nadree-api-test-handoff-2026-10-01.md`를 참고합니다. Firebase ID Token, access token, refresh token, PayPal 자격증명과 실제 FCM 토큰은 Swagger 설명에 기록하지 않습니다.
"""


def create_app(settings=None, db=None, limiter=None, mailer=None, fcm=None, locations=None, customer_auth=None):
    settings = settings or Settings()
    if settings.env == "production" and (len(settings.jwt_secret.get_secret_value().encode()) < 32
                                         or not settings.database_url.get_secret_value()
                                         or not settings.redis_url.get_secret_value()):
        raise RuntimeError("Production database, signing key and rate limiter are required")

    @asynccontextmanager
    async def lifespan(app):
        yield
        if app.state.db.engine is not None:
            app.state.db.engine.dispose()
        client = getattr(app.state.limiter, "redis", None)
        if client is not None:
            client.close()
        app.state.paypal.close()
        close_fcm = getattr(app.state.fcm, "close", None)
        if close_fcm is not None:
            close_fcm()
        close_locations = getattr(app.state.locations, "close", None)
        if close_locations is not None:
            close_locations()

    application = FastAPI(
        title="Nadree API",
        description=OPENAPI_DESCRIPTION,
        version="0.1.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=OPENAPI_TAGS,
        contact={"name": "Nadree API"},
        lifespan=lifespan,
        responses={code: {"model": Error} for code in [401, 403, 404, 409, 422, 429, 503]})
    application.state.settings = settings
    application.state.db = db or Database(settings.database_url.get_secret_value())
    application.state.limiter = limiter or RateLimiter(settings.redis_url.get_secret_value())
    application.state.mailer = mailer or PasswordMailer(settings)
    application.state.fcm = fcm or FcmSender(settings)
    application.state.customer_auth = customer_auth or CustomerFirebaseAuth(settings)
    application.state.locations = locations or VehicleLocations(settings)
    application.state.paypal = PayPalClient(settings)
    install_handlers(application)

    @application.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @application.get("/health/live", tags=["W00 Health"])
    def live():
        return {"status": "ok", "service": "nadree-api"}

    @application.get("/health/ready", tags=["W00 Health"])
    def ready():
        engine = application.state.db.engine
        if engine is None:
            raise Problem(503, "DATABASE_NOT_CONFIGURED")
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            limitations = check_schema(application.state.db, connection)
        if not getattr(application.state.fcm, "configured", True):
            limitations.append("FCM_NOT_CONFIGURED")
        if settings.env == "production" and not application.state.customer_auth.configured:
            raise Problem(503, "CUSTOMER_FIREBASE_AUTH_NOT_CONFIGURED")
        sign_access(settings, "readiness", "readiness", 0)
        application.state.limiter.check_connection()
        application.state.mailer.check_configuration()
        return {"status": "ok", "limitations": limitations}

    application.include_router(auth_router)
    application.include_router(admin_signup_router)
    application.include_router(management_router)
    application.include_router(delivery_router)
    application.include_router(pricing_router)
    application.include_router(vehicles_router)
    application.include_router(rentals_router)
    application.include_router(readmodels_router)
    application.include_router(paypal_router)
    application.include_router(customer_rentals_router)
    application.include_router(customer_users_router)

    def custom_openapi():
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
            tags=OPENAPI_TAGS,
        )
        components = schema.get("components", {}).get("schemas", {})
        for name, example in OPENAPI_EXAMPLES.items():
            if name in components:
                components[name]["example"] = example
        for path, operations in schema.get("paths", {}).items():
            for method, operation in operations.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                key = (method.upper(), path)
                request = operation.get("requestBody")
                if request:
                    content = request.get("content", {}).get("application/json")
                    if content:
                        ref = content.get("schema", {}).get("$ref", "").rsplit("/", 1)[-1]
                        example = components.get(ref, {}).get("example")
                        if example is not None:
                            content["example"] = example
                if key in OPENAPI_REQUEST_EXAMPLES:
                    operation["requestBody"] = {
                        "required": True,
                        "content": {"application/json": {
                            "schema": {"type": "object"},
                            "example": OPENAPI_REQUEST_EXAMPLES[key],
                        }},
                    }
                response_example = OPENAPI_RESPONSE_EXAMPLES.get(key)
                if response_example is not None:
                    response = operation.get("responses", {}).get("200")
                    if response is not None:
                        response.setdefault("content", {}).setdefault("application/json", {})["example"] = response_example
        application.openapi_schema = schema
        return schema

    application.openapi = custom_openapi
    return application


app = create_app()
