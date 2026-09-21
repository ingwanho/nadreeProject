from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NADREE_", env_file=".env", extra="ignore")
    env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr("")
    redis_url: SecretStr = SecretStr("")
    jwt_secret: SecretStr = SecretStr("")
    jwt_issuer: str = "nadree-api"
    jwt_audience: str = "nadreego"
    user_jwt_audience: str = "nadri"
    access_minutes: int = 15
    user_access_minutes: int = 60
    refresh_days: int = 30
    rental_currency: str = "USD"
    business_timezone: str = "Asia/Makassar"
    field_encrypt_key: SecretStr = SecretStr("")
    qr_hash_key: SecretStr = SecretStr("")
    availability_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    firestore_project: str = ""
    # FCM uses a separate Firebase project from vehicle-location reads.
    fcm_credential_type: str = "service_account"
    fcm_project_id: str = ""
    fcm_private_key_id: str = ""
    fcm_private_key: SecretStr = SecretStr("")
    fcm_client_email: str = ""
    fcm_client_id: str = ""
    fcm_auth_uri: str = "https://accounts.google.com/o/oauth2/auth"
    fcm_token_uri: str = "https://oauth2.googleapis.com/token"
    fcm_auth_provider_x509_cert_url: str = "https://www.googleapis.com/oauth2/v1/certs"
    fcm_client_x509_cert_url: str = ""
    fcm_universe_domain: str = "googleapis.com"
    paypal_environment: Literal["SANDBOX", "LIVE"] = "SANDBOX"
    paypal_client_id: SecretStr = SecretStr("")
    paypal_client_secret: SecretStr = SecretStr("")
    paypal_webhook_id: SecretStr = SecretStr("")
    paypal_merchant_id: str = ""
    paypal_unpaid_minutes: int = Field(default=180, ge=1, le=10080)
    inventory_horizon_days: int = Field(default=180, ge=1, le=366)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_tls: Literal["starttls", "ssl"] = "starttls"

    @field_validator("business_timezone")
    @classmethod
    def valid_timezone(cls, value):
        ZoneInfo(value)
        return value

    @field_validator("access_minutes", "user_access_minutes", "refresh_days")
    @classmethod
    def positive(cls, value):
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @field_validator("rental_currency")
    @classmethod
    def valid_currency(cls, value):
        if not isinstance(value, str) or len(value) != 3 or not value.isupper() or not value.isalpha():
            raise ValueError("currency must be an ISO uppercase code")
        return value
