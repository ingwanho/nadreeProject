from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Status(BaseModel):
    status: Literal["success"] = "success"


class AdminAccountDeletion(Status):
    deleted: Literal[True] = True
    scope: Literal["SELF", "SUBTREE"]
    spotMasterId: str
    deletedAdminCount: int = Field(ge=1)
    deletedSpotCount: int = Field(ge=0)


class DeletionOutstandingWork(BaseModel):
    pendingReservations: int = 0
    activeRentals: int = 0
    pendingReturns: int = 0
    pendingRecovery: int = 0
    pendingRefunds: int = 0
    pendingExternalSettlements: int = 0


class AccountDeletionContext(Status):
    scope: Literal["SELF", "SUBTREE"]
    directShopName: str
    affectedAdminCount: int
    affectedShopCount: int
    confirmationToken: str
    confirmationExpiresAt: datetime
    outstandingWork: DeletionOutstandingWork
    canSubmitRequest: bool = True
    canExecuteWithdrawal: bool
    activeRequestId: str | None = None


class AccountDeletionRequestResult(Status):
    requestId: str
    requestAccepted: bool = True
    requestState: Literal["WAITING_VERIFICATION", "WAITING_OBLIGATIONS", "WAITING_RECONFIRMATION",
                          "PROCESSING", "RETRYING", "ACTION_REQUIRED", "COMPLETED", "COMPLETED_WITH_RETENTION"]
    scope: Literal["SELF", "SUBTREE"]
    receivedAt: datetime
    identityVerifiedAt: datetime
    eligibleAt: datetime | None = None
    processingDueAt: datetime | None = None
    completedAt: datetime | None = None
    accessState: Literal["ACTIVE", "PENDING", "LIMITED_TO_SETTLEMENT", "REVOKED"]
    personalDataState: Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETED"]
    outstandingWork: DeletionOutstandingWork
    affectedAdminCount: int
    affectedShopCount: int
    nextAction: Literal["NONE", "SETTLE_OUTSTANDING_WORK", "RELOAD_AND_RECONFIRM",
                        "REVIEW_DATA_AND_RETENTION", "CONTACT_OPERATOR"]
    notificationChannel: str = "REGISTERED_EMAIL"
    completionScope: str | None = None
    retainedData: list[dict[str, Any]] = Field(default_factory=list)
    residualCopies: list[dict[str, Any]] = Field(default_factory=list)
    receiptExpiresAt: datetime | None = None
    message: str


class Error(BaseModel):
    status: Literal["fail"] = "fail"
    errorCode: str
    paymentId: int | None = None
    clientRequestId: str | None = None
    requestStatus: Literal["ACCEPTED", "REJECTED", "PROCESSING", "UNKNOWN"] | None = None
    requestFinal: bool | None = None
    retrySameRequest: bool | None = None
    canStartNewRequest: bool | None = None
    requestAccepted: bool | None = None
    nextAction: str | None = None


class ShopPayPalMerchantResult(Status):
    onlinePaymentEnabled: bool = False
    newReservationPaymentMethod: Literal["EXTERNAL", "PAYPAL"] = "EXTERNAL"
    spotMasterId: str
    merchantId: str | None
    paymentEnvironment: Literal["SANDBOX", "LIVE"] | None


class Admin(BaseModel):
    adminId: str
    name: str | None
    email: str | None
    role: Literal["rental_primary_admin", "rental_manager"]


class SignedInAdmin(Admin):
    spotMasterId: str | None = Field(
        description="Administrator membership key from MSP_ADMIN.primary_spot_master_id, referencing MSP_SPOT_MASTER.spot_master_id at any hierarchy level. This is not the normalized MSP_SPOT.spot_id.")


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
    priceOptionId: str | None = None
    totalPrice: int | float | None = None
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


class ReceiptInfo(BaseModel):
    requestDeadline: str | None = None
    requestType: Literal["ADVANCE", "ONSITE"] = "ADVANCE"
    customerReceiptRequired: bool = False
    handedOverAt: str | None = None
    receiptDeadline: str | None = None
    receivedAt: str | None = None
    canReceive: bool = False
    receiptBlockedReason: str | None = None
    vehicleRecoveryRequired: bool = False


class CustomerRecord(ReceiptInfo):
    paymentMethod: Literal["EXTERNAL", "PAYPAL"] | None = None
    onlinePaymentEnabled: bool = False
    paymentStatus: str | None = None
    paymentDeadline: str | None = None
    canPay: bool = False
    canCapture: bool = False
    cannotPayReason: str | None = None
    pickupLocationSnapshot: CustomerLocation | None = None
    returnLocationSnapshot: CustomerLocation | None = None
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


class CustomerAccountDeletion(Status):
    deleted: bool


class PassportUploadResult(Status):
    bookedNo: str
    available: bool
    contentType: str
    sizeBytes: int
    uploadedAt: str
    downloadPath: str


class CustomerAvailabilityItem(BaseModel):
    canRequest: bool
    cannotRequestReason: str | None
    # 앱의 shopId는 렌탈 지점의 영구 식별자인 spotMasterId와 같은 값이다.
    shopId: str
    modelId: str
    spot: CustomerSpot
    model: CustomerModel
    price: CustomerPrice


class CustomerAvailability(Status):
    newReservationPaymentMethod: Literal["EXTERNAL", "PAYPAL"] = "EXTERNAL"
    onlinePaymentEnabled: bool = False
    items: list[CustomerAvailabilityItem]


class CustomerRequest(Status):
    paymentMethod: Literal["EXTERNAL", "PAYPAL"]
    onlinePaymentEnabled: bool
    paymentDeadline: str | None = None
    canPay: bool = False
    canCapture: bool = False
    reservationId: str
    bookingId: str
    bookedNo: str
    reservationStatus: str
    vehicleAssignmentStatus: str
    paymentAvailability: str
    paymentStatus: str | None
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


class CustomerReservationDetail(Status):
    item: CustomerRecord


class CustomerOnsiteResult(Status):
    item: CustomerRecord | None = None
    clientRequestId: str
    requestStatus: Literal["ACCEPTED", "REJECTED", "PROCESSING", "UNKNOWN"]
    requestFinal: bool
    retrySameRequest: bool
    canStartNewRequest: bool
    errorCode: str | None = None


class CustomerQrLookup(Status, ReceiptInfo):
    vehicleId: str
    vehicleNo: str | None
    vehicleStatus: str | None
    model: CustomerModel
    spot: CustomerSpot
    reservationId: str | None
    reservationStatus: str | None
    vehicleMatch: Literal["ASSIGNED", "MODEL_PENDING"] | None
    availableActions: list[Literal["ONSITE_QUOTE", "WAIT_APPROVAL", "WAIT_HANDOVER", "CONFIRM_RECEIPT"]]


class CustomerOnsiteQuote(Status):
    vehicleId: str
    spot: CustomerSpot
    startDate: str
    returnDate: str
    price: CustomerPrice
    quoteExpiresAt: str
    quoteToken: str


class CustomerPayment(Status):
    paymentMethod: Literal["EXTERNAL", "PAYPAL"] = "PAYPAL"
    onlinePaymentEnabled: bool = False
    paymentStateSource: Literal["DATABASE"] = "DATABASE"
    paymentUpdatedAt: str | None = None
    providerStateChecked: bool = False
    paymentId: int
    reservationId: str | None = None
    bookingId: str | None = None
    shopId: str | None = None
    paymentStatus: str
    refundStatus: str = "NONE"
    refundedAmount: int | float | None = None
    refundRequestedAmount: int | float | None = None
    paypalOrderId: str | None = None
    paypalCaptureId: str | None = None
    approvalUrl: str | None = None
    paypalOrderStatus: str | None = None
    nextAction: Literal["APPROVE", "CAPTURE", "RETRY_CAPTURE", "WAIT", "DONE", "REVIEW", "NONE"] = "WAIT"
    canCapture: bool = False
    totalPrice: int | float
    serverTotalPrice: int | float
    currency: str
    paymentDeadline: str | None = None
    canPay: bool = False
    cannotPayReason: str | None = None
    payment: dict[str, Any] | None = None


class CustomerCancellation(Status):
    reservationId: str
    bookedNo: str
    reservationStatus: str
    refundStatus: str
    refundRequestedAmount: int | float
    refundReason: str


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


class ShopProfile(ShopResult):
    spotCode: str
    shopName: str
    companyId: str
    contact: str | None
    email: str | None
    address: str | None
    location: str | None
    lat: float | None
    lng: float | None
    addressDetail: str | None
    zipCode: str | None
    directions: str | None
    introduction: str | None


class HierarchyItem(BaseModel):
    spot_master_id: str
    unit_code: str
    spot_name: str = Field(description="The node's own MSP_SPOT_MASTER.unit_name, retained under the existing response field name.")
    hierarchy_level: str | None
    org_name: str | None
    region_name: str | None
    is_active: bool
    manager_name: str | None
    companyId: str
    parentSpotMasterId: str | None
    canEditProfile: bool
    canEditPricing: bool
    canEditDelivery: bool
    canCreateChild: bool = Field(
        description="Whether the current primary administrator can create a child at the next supported level. Supported parent levels are org, region, and local.")


class Hierarchy(BaseModel):
    items: list[HierarchyItem]
    total: int
    currentSpotMasterId: str
    companyId: str
    isCompanyPrimary: bool


class CreatedSpot(BaseModel):
    spot_id: str = Field(
        description="Created MSP_SPOT_MASTER.spot_master_id. This existing response field carries the master key for every hierarchy level.")
    unit_code: str
    spot_name: str = Field(description="The created node's own unit_name. Non-leaf nodes do not store this value in the master table's spot_name column.")
    hierarchy_level: str = Field(
        description="Actual level derived from the locked parent master: org creates region, region creates local, and local creates spot, regardless of the legacy unit_type hint.")
    phone: str | None
    biz_reg_num: str | None
    address: str | None
    zip_code: str | None
    lat: float | None
    lng: float | None
    contract_start: date | None
    contract_end: date | None
    is_active: bool
    inviteCode: str | None = Field(default=None,
        description="One-time invitation code containing 8 uppercase letters and digits for newly created shops.")
    email: str | None = None
    parentSpotMasterId: str | None = Field(default=None,
        description="MSP_SPOT_MASTER.spot_master_id of the parent used to determine the child level.")


class Applicant(BaseModel):
    email: str
    name: str | None


class Applicants(Status):
    admins: list[Applicant]


class AdminSignupResult(Status):
    adminId: str
    requestId: str | None
    spotMasterId: str
    requestStatus: Literal["REQUESTED"] | None
    accountStatus: Literal["ACTIVE", "PENDING_APPROVAL"]
