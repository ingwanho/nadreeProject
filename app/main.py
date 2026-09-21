from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy import text

from app.auth import router as auth_router
from app.admin_signup import router as admin_signup_router
from app.config import Settings
from app.db import Database
from app.errors import Problem, install_handlers
from app.fcm import FcmSender
from app.management import router as management_router
from app.mail import PasswordMailer
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
    {"name": "W00 Health", "description": "서비스 상태와 의존성 확인"},
    {"name": "W01 Accounts", "description": "관리자 로그인·가입 신청·토큰·프로필"},
    {"name": "W02 Organizations and admins", "description": "지점 계층과 관리자 권한"},
    {"name": "W03 Vehicles and QR", "description": "차량·QR·센서 관리"},
    {"name": "W04 Pricing", "description": "차량 가격과 렌탈 티어"},
    {"name": "W05 Delivery", "description": "배송 지역과 배송비"},
    {"name": "W06 Reservations and rentals", "description": "예약·렌트·인계·반납"},
    {"name": "W07 Dashboard and calendar", "description": "운영 현황과 캘린더 조회"},
    {"name": "W08 PayPal webhook", "description": "PayPal 결제·환불·웹훅"},
    {"name": "Nadri customer users", "description": "나드리 고객 UID 로그인·프로필·토큰"},
    {"name": "Nadri customer rentals", "description": "나드리 차량 조회·예약·결제·렌트 이력"},
]


def create_app(settings=None, db=None, limiter=None, mailer=None, fcm=None):
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

    application = FastAPI(
        title="Nadree API",
        description="나드리·나드리고 렌탈 API. `/docs`는 Swagger UI, `/redoc`은 ReDoc 문서입니다.",
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
    return application


app = create_app()
