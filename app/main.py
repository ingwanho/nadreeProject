from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text

from app.auth import router as auth_router
from app.admin_signup import router as admin_signup_router
from app.chat import FirebaseChat, router as chat_router
from app.chat_push_endpoint import GooglePushIdentity, router as chat_push_router
from app.config import Settings
from app.images import ImageURLs
from app.db import Database
from app.errors import Problem, install_handlers
from app.fcm import FcmSender
from app.firebase_auth import CustomerFirebaseAuth
from app.management import router as management_router
from app.admin_customers import router as admin_customers_router
from app.notifications import router as notifications_router
from app.mail import PasswordMailer
from app.locations import VehicleLocations
from app.openapi_examples import (OPENAPI_EXAMPLES, OPENAPI_REQUEST_EXAMPLES,
                                   OPENAPI_RESPONSE_EXAMPLES, OPENAPI_STATUS_EXAMPLES)
from app.delivery import router as delivery_router
from app.paypal import PayPalClient, router as paypal_router
from app.paypal_onboarding import router as paypal_onboarding_router
from app.passport import PassportStorage
from app.customer_rentals import router as customer_rentals_router, user_router as customer_users_router
from app.customer_qr import router as customer_qr_router
from app.pricing import router as pricing_router
from app.readmodels import router as readmodels_router
from app.rentals import router as rentals_router
from app.vehicles import router as vehicles_router
from app.responses import Error
from app.account_deletions import router as account_deletions_router
from app.account_deletion_store import DeletionStore
from app.schema_check import check_schema
from app.security import RateLimiter, sign_access

OPENAPI_TAGS = [
    {"name": "W00 Health", "description": "Service and dependency health. Check `/health/live` and `/health/ready` before testing."},
    {"name": "W01 Accounts", "description": "Administrator sign-in, registration requests, tokens, and profiles"},
    {"name": "W02 Organizations and admins", "description": "Branch hierarchy and administrator permissions"},
    {"name": "W03 Vehicles and QR", "description": "Vehicle, QR, and sensor management"},
    {"name": "W04 Pricing", "description": "Vehicle prices and rental pricing tiers"},
    {"name": "W05 Delivery", "description": "Delivery regions and fees"},
    {"name": "W06 Reservations and rentals", "description": "Reservations, rentals, handover, and returns. Passport routes remain disabled. Seeded reservations use `NRTEST-RES-*`; vehicles use `NRTEST-VEHICLE-*`."},
    {"name": "W07 Dashboard and calendar", "description": "Operational dashboard and calendar views"},
    {"name": "W08 PayPal webhook", "description": "PayPal payments, refunds, and webhooks"},
    {"name": "Nadree customer users", "description": "Nadree customer UID sign-in, profiles, and tokens. Sign-in requires both a Firebase ID Token and the UID in the request body."},
    {"name": "Nadree customer rentals", "description": "Nadree vehicle listings, reservations, payments, and rental history. Use test branch `00000000-0000-4000-8000-000000000101` and web test models `NRTEST-WEB-MODEL-125` and `NRTEST-WEB-MODEL-ND`."},
]

OPENAPI_DESCRIPTION = """
Rental API for Nadree and NadreeGo.

## Getting started

1. Check the process status at `/health/live`.
2. Confirm that `/health/ready` returns `status=ok`.
3. Administrator APIs use `/nadreego`; customer APIs use `/api/v1/nadree`.
4. Follow each operation's schemas for request and response fields.

## Test data conventions

Values prefixed with `NRTEST-` identify seeded test data. Keep them separate from production data.

- Test branch (`spotMasterId`/`shopId`): `00000000-0000-4000-8000-000000000101`
- Test models: `NRTEST-MODEL-125` (Honda Vario 125, 125cc), `NRTEST-MODEL-155` (Yamaha NMAX 155, 155cc)
- Test vehicles: `NRTEST-VEHICLE-301` (available), `NRTEST-VEHICLE-302` (maintenance), `NRTEST-VEHICLE-303` (active rental), `NRTEST-VEHICLE-304` (future approved reservation)
- Web test models: `NRTEST-WEB-MODEL-125` (Honda Vario Web Test 125, 125cc, BASIC/PREMIUM), `NRTEST-WEB-MODEL-ND` (SYM Cruiser No Delivery Test, delivery unavailable)
- Web test vehicles: `NRTEST-WEB-BASIC-125`, `NRTEST-WEB-PREMIUM-125` (45 USD per day), `NRTEST-WEB-NODELIVERY`
- Web test delivery regions: `NRTEST-KUTA` (20 USD round trip), `NRTEST-CANGGU` (30 USD round trip)
- Reservation status examples: `NRTEST-RES-REQ-001`, `NRTEST-RES-APP-001`, `NRTEST-RES-PENDING-001`, `NRTEST-RES-REJECT-001`, `NRTEST-RES-CANCEL-001`, `NRTEST-RES-EXPIRED-001`, `NRTEST-RES-HAND-001`, `NRTEST-RES-RETURN-001`
- Test currency: `USD`. The standard 125cc BASIC rate is 25 USD per day. The web 125cc model offers BASIC at 25 USD or PREMIUM at 45 USD per day. Canggu round-trip delivery costs 15 + 15 USD.

See `docs/nadree-api-test-handoff-2026-10-01.md` in the repository for the full test sequence and expected results. Do not include Firebase ID Tokens, access tokens, refresh tokens, PayPal credentials, or real FCM tokens in Swagger descriptions.
"""


def create_app(settings=None, db=None, limiter=None, mailer=None, fcm=None, locations=None, customer_auth=None,
               passport_storage=None, deletion_store=None, images=None):
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
        app.state.chat_push_identity.close()
        close_images = getattr(app.state.images, "close", None)
        if close_images is not None:
            close_images()

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
        responses={code: {"model": Error} for code in [401, 403, 404, 409, 410, 422, 429, 503]})
    cors_origins = [origin.strip().rstrip("/") for origin in settings.cors_origins.split(",") if origin.strip()]
    if cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Refresh-Token", "X-FCM-Token",
                           "Idempotency-Key", "Deletion-Receipt-Token"],
            expose_headers=["Cache-Control", "Content-Disposition", "Retry-After"],
        )
    application.state.settings = settings
    application.state.images = images or ImageURLs(settings)
    application.state.db = db or Database(settings.database_url.get_secret_value())
    application.state.limiter = limiter or RateLimiter(settings.redis_url.get_secret_value())
    application.state.mailer = mailer or PasswordMailer(settings)
    application.state.fcm = fcm or FcmSender(settings)
    application.state.customer_auth = customer_auth or CustomerFirebaseAuth(settings)
    application.state.chat = FirebaseChat(settings)
    application.state.deletions = deletion_store or DeletionStore(settings)
    application.state.chat_push_identity = GooglePushIdentity(settings)
    application.state.locations = locations or VehicleLocations(settings)
    application.state.passport_storage = passport_storage or PassportStorage(settings.passport_storage_root)
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
        from app.receipt import require_schema
        require_schema(application.state.db)
        from app.onsite_requests import require_schema as require_request_schema
        require_request_schema(application.state.db)
        if not getattr(application.state.fcm, "configured", True):
            limitations.append("FCM_NOT_CONFIGURED")
        if settings.env == "production" and not application.state.customer_auth.configured:
            raise Problem(503, "CUSTOMER_FIREBASE_AUTH_NOT_CONFIGURED")
        sign_access(settings, "readiness", "readiness", 0)
        application.state.limiter.check_connection()
        application.state.mailer.check_configuration()
        return {"status": "ok", "limitations": limitations}

    application.include_router(auth_router)
    application.include_router(account_deletions_router)
    application.include_router(admin_signup_router)
    application.include_router(chat_router)
    application.include_router(chat_push_router)
    application.include_router(management_router)
    application.include_router(admin_customers_router)
    application.include_router(notifications_router)
    application.include_router(delivery_router)
    application.include_router(pricing_router)
    application.include_router(vehicles_router)
    application.include_router(rentals_router)
    application.include_router(readmodels_router)
    application.include_router(paypal_router)
    application.include_router(paypal_onboarding_router)
    application.include_router(customer_rentals_router)
    application.include_router(customer_qr_router)
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
                for status, examples in OPENAPI_STATUS_EXAMPLES.get(key, {}).items():
                    response = operation["responses"].setdefault(str(status), {
                        "description": "Response for this status", "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"}}}})
                    content = response.setdefault("content", {}).setdefault("application/json", {})
                    content.pop("example", None)
                    content["examples"] = {name: {"value": value} for name, value in examples.items()}
        application.openapi_schema = schema
        return schema

    application.openapi = custom_openapi
    return application


app = create_app()
