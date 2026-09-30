from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


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


class CustomerProfile(BaseModel):
    uidToken: str
    name: str | None = None
    age: int | None = None
    gender: str | None = None
    nationality: str | None = None


class CustomerLocation(BaseModel):
    address: str | None = None
    zipCode: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class CustomerSpot(BaseModel):
    shopId: str
    spotMasterId: str
    spotCode: str | None = None
    unitCode: str | None = None
    spotName: str | None = None
    phone: str | None = None
    location: CustomerLocation


class CustomerModel(BaseModel):
    modelId: str
    brand: str | None = None
    modelName: str | None = None
    cc: int | None = None
    vehicleType: str | None = None
    modelImageKey: str | None = None


class CustomerPricingTier(BaseModel):
    priceType: str
    tierType: str | None = None
    minCc: int | None = None
    maxCc: int | None = None
    dailyPriceFrom: int | float | None = None
    dailyPriceTo: int | float | None = None


class CustomerPrice(BaseModel):
    currency: str
    rentalDays: int | None = None
    dailyFrom: int | float | None = None
    dailyTo: int | float | None = None
    dailyPriceFrom: int | float | None = None
    dailyPriceTo: int | float | None = None
    rentalFrom: int | float | None = None
    rentalTo: int | float | None = None
    pricingTiers: list[CustomerPricingTier] = Field(default_factory=list)
    deliveryStart: int | float | None = None
    deliveryReturn: int | float | None = None
    deliveryTotal: int | float | None = None
    deliveryStartFee: int | float | None = None
    deliveryReturnFee: int | float | None = None
    deliveryTotalFee: int | float | None = None
    totalOptions: list[int | float] = Field(default_factory=list)
    totalFrom: int | float | None = None
    totalTo: int | float | None = None
    requestedTotal: int | float | None = None
    calculatedTotalFrom: int | float | None = None
    calculatedTotalTo: int | float | None = None
    finalTotal: int | float | None = None


class CustomerDelivery(BaseModel):
    deliveryRequestType: str
    deliveryRegionId: int | None = None
    pickupLocation: str | None = None
    returnLocation: str | None = None
    startDeliveryFee: int | float | None = None
    returnDeliveryFee: int | float | None = None
    deliveryTotalFee: int | float | None = None


class CustomerRecord(BaseModel):
    recordType: Literal["RESERVATION", "RENTAL"]
    reservationId: str | None = None
    bookingId: str | None = None
    rentalContractId: str | None = None
    bookedNo: str
    reservationStatus: str | None = None
    rentalStatus: str | None = None
    vehicleAssignmentStatus: str | None = None
    shopId: str
    spotMasterId: str
    modelId: str | None = None
    paymentAvailability: str | None = None
    spot: CustomerSpot
    model: CustomerModel | None = None
    startDate: str | None = None
    returnDate: str | None = None
    actualStartTime: str | None = None
    actualEndTime: str | None = None
    deliveryRequestType: str
    pickupLocation: str | None = None
    returnLocation: str | None = None
    delivery: CustomerDelivery
    price: CustomerPrice
    payment: dict[str, Any] | None = None


class CustomerUser(CustomerProfile):
    ongoingRequests: list[CustomerRecord] = Field(default_factory=list)


class CustomerLogin(Tokens):
    isNewUser: bool
    user: CustomerUser


class CustomerProfileResult(Status):
    user: CustomerProfile


class CustomerAvailabilityItem(BaseModel):
    # 앱의 shopId는 렌탈 지점의 영구 식별자인 spotMasterId와 같은 값이다.
    shopId: str
    modelId: str
    spot: CustomerSpot
    model: CustomerModel
    price: CustomerPrice


class CustomerAvailability(Status):
    items: list[CustomerAvailabilityItem]


class CustomerRequest(Status):
    reservationId: str
    bookingId: str
    bookedNo: str
    reservationStatus: str
    vehicleAssignmentStatus: str
    paymentAvailability: str
    paymentStatus: str
    shopId: str
    spotMasterId: str
    modelId: str
    totalPrice: int | float
    currency: str
    deliveryRequestType: str
    spot: CustomerSpot
    model: CustomerModel
    price: CustomerPrice


class CustomerPage(Status):
    items: list[CustomerRecord]
    page: int
    pageSize: int
    totalCount: int
    hasNext: bool


class CustomerPayment(Status):
    paymentId: int
    reservationId: str | None = None
    bookingId: str | None = None
    shopId: str | None = None
    paymentStatus: str
    paypalOrderId: str | None = None
    paypalCaptureId: str | None = None
    approvalUrl: str | None = None
    totalPrice: int | float
    serverTotalPrice: int | float
    currency: str
    payment: dict[str, Any] | None = None


class CustomerCancellation(Status):
    reservationId: str
    bookedNo: str
    reservationStatus: str
    refundStatus: str


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
    inviteCode: str | None = None


class Applicant(BaseModel):
    email: str
    name: str | None


class Applicants(Status):
    admins: list[Applicant]


class AdminSignupResult(Status):
    adminId: str
    requestId: str
    spotMasterId: str
    requestStatus: Literal["REQUESTED"] = "REQUESTED"
