from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, model_validator

Text100 = Annotated[str, Field(min_length=1, max_length=100)]
Identifier = Annotated[str, Field(min_length=1, max_length=36)]
Token = Annotated[str, Field(min_length=1, max_length=512)]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Body):
    email: Annotated[str, Field(min_length=1, max_length=200)]
    password: SecretStr = Field(min_length=1, max_length=200)
    fcmToken: Token | None = None


class AdminSignup(Body):
    """RiderLog 공용 관리자 계정 생성과 렌탈 가입 신청 입력."""
    loginId: Annotated[str, Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_.@+-]+$")]
    email: EmailStr = Field(max_length=200)
    password: SecretStr = Field(min_length=8, max_length=200)
    name: Text100
    phone: Annotated[str, Field(min_length=1, max_length=20)] | None = None
    representativeEmail: EmailStr | None = Field(default=None, max_length=200)
    inviteCode: Annotated[str, Field(min_length=1, max_length=64)] | None = None

    @model_validator(mode="after")
    def target(self):
        if self.representativeEmail is None and self.inviteCode is None:
            raise ValueError("representativeEmail or inviteCode is required")
        return self


class Profile(Body):
    name: Text100 | None = None
    email: Annotated[str, Field(min_length=3, max_length=200)] | None = None
    password: SecretStr | None = Field(default=None, min_length=8, max_length=200)
    phone: Annotated[str, Field(min_length=1, max_length=20)] | None = None
    fcmToken: Token | None = None


class FcmToken(Body):
    fcmToken: Token


class SpotCode(Body):
    spotCode: Annotated[str, Field(min_length=1, max_length=64)]


class Email(Body):
    email: EmailStr = Field(max_length=200)


class AdminId(Body):
    adminId: Identifier


class Shop(Body):
    shopName: Text100 | None = None
    location: Annotated[str, Field(max_length=500)] | None = None
    introduction: Annotated[str, Field(max_length=500)] | None = None
    contact: Annotated[str, Field(max_length=20)] | None = None
    email: Annotated[str, Field(max_length=200)] | None = None
    deliveryServiceType: Literal["NONE", "START_ONLY", "START_AND_RETURN"] | None = None


class RequestAction(Email):
    action: Literal["APPROVE", "REJECT"]
    spotMasterId: Identifier | None = None


class SpotCreate(Body):
    spot_name: Text100
    unit_type: Literal["org", "region", "local", "spot", "team", "agency"]
    parent_spot_id: Identifier
    phone: Annotated[str, Field(max_length=20)] | None = None
    biz_reg_num: Annotated[str, Field(max_length=30)] | None = None
    address: Annotated[str, Field(max_length=500)] | None = None
    address_detail: Annotated[str, Field(max_length=200)] | None = None
    zip_code: Annotated[str, Field(max_length=10)] | None = None
    lat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    lng: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    contract_start: date | None = None
    contract_end: date | None = None

    @model_validator(mode="after")
    def dates_ordered(self):
        if self.contract_start and self.contract_end and self.contract_start > self.contract_end:
            raise ValueError("invalid date interval")
        return self
