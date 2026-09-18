from datetime import date
from typing import Literal

from pydantic import BaseModel


class Status(BaseModel):
    status: Literal["success"] = "success"


class Error(BaseModel):
    status: Literal["fail"] = "fail"
    errorCode: str


class Admin(BaseModel):
    adminId: str
    name: str | None
    email: str | None
    role: Literal["rental_primary_admin", "rental_manager"]


class SignedInAdmin(Admin):
    spotMasterId: str | None


class Tokens(Status):
    accessToken: str
    refreshToken: str


class SignedIn(Tokens):
    admin: SignedInAdmin


class ProfileResult(Status):
    adminId: str
    name: str | None
    email: str | None


class SpotResult(Status):
    spotMasterId: str
    spotName: str
    unitCode: str
    isDeliverySupported: bool


class PrimaryResult(Status):
    primaryAdminId: str


class Admins(Status):
    admin: list[Admin]


class ShopResult(Status):
    spotMasterId: str
    deliveryServiceType: Literal["NONE", "START_ONLY", "START_AND_RETURN"]


class HierarchyItem(BaseModel):
    spot_master_id: str
    unit_code: str
    spot_name: str
    hierarchy_level: str | None
    org_name: str | None
    region_name: str | None
    is_active: bool
    manager_name: str | None


class Hierarchy(BaseModel):
    items: list[HierarchyItem]
    total: int


class CreatedSpot(BaseModel):
    spot_id: str
    unit_code: str
    spot_name: str
    hierarchy_level: str
    phone: str | None
    biz_reg_num: str | None
    address: str | None
    zip_code: str | None
    lat: float | None
    lng: float | None
    contract_start: date | None
    contract_end: date | None
    is_active: bool


class Applicant(BaseModel):
    email: str
    name: str | None


class Applicants(Status):
    admins: list[Applicant]
