from datetime import date as Date
from typing import Annotated, Literal

from pydantic import Field, SecretStr, StrictBool, model_validator

from app.schemas import Body, Identifier, Token

Positive = Annotated[int, Field(strict=True, ge=1)]
Money = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
Cc = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
Plate = Annotated[str, Field(min_length=1, max_length=25, pattern=r"\S")]
Spot = Annotated[str, Field(min_length=1, max_length=60)]
ModelId = Annotated[str, Field(min_length=1, max_length=50)]
VehicleState = Literal["AVAILABLE", "ON_RENT", "MAINTENANCE", "DISABLED"]
ReservationState = Literal["REQUESTED", "APPROVED", "HANDED_OVER", "RETURNED", "REJECTED", "CANCELED", "EXPIRED"]
RentalState = Literal["ON_RENT", "OVERDUE", "RETURNED", "CANCELED"]
Reason = Annotated[str, Field(max_length=200)]
Uid = Annotated[str, Field(min_length=1, max_length=36, pattern=r"^\S+$")]
Currency = Annotated[str, Field(min_length=3, max_length=3, pattern=r"[A-Z]{3}")]
Address = Annotated[str, Field(min_length=1, max_length=500)]


class Page(Body):
    page: Positive
    pageSize: Annotated[int, Field(strict=True, ge=1, le=100)]


class Calendar(Page):
    spotCode: Spot | None = None
    startDate: Date
    endDate: Date
    modelId: ModelId | None = None
    vehicleStatus: VehicleState | None = None
    keyword: Annotated[str, Field(max_length=100)] | None = None

    @model_validator(mode="after")
    def dates(self):
        if not 0 < (self.endDate - self.startDate).days <= 42:
            raise ValueError("calendar interval must be 1 to 42 days")
        return self


class Operations(Page):
    keyword: Annotated[str, Field(max_length=100)] | None = None
    startDate: Date | None = None
    endDate: Date | None = None
    recordType: Literal["RESERVATION", "RENTAL"] | None = None
    reservationStatus: ReservationState | None = None
    rentalStatus: RentalState | None = None

    @model_validator(mode="after")
    def filters(self):
        if (self.startDate is None) != (self.endDate is None):
            raise ValueError("both dates required")
        if self.startDate and self.startDate > self.endDate:
            raise ValueError("invalid period")
        if self.recordType == "RESERVATION" and self.rentalStatus:
            raise ValueError("contradictory filters")
        return self


class VehicleNumber(Body):
    vehicleNumber: Plate


class VehicleCreate(Body):
    sensorId: Identifier | None = None
    qrToken: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    brand: Annotated[str, Field(min_length=1, max_length=50)]
    vehicleName: Annotated[str, Field(min_length=1, max_length=50)]
    modelId: ModelId
    plateNumber: Plate
    vehicleImageKey: Annotated[str, Field(max_length=500)] | None = None

    @model_validator(mode="after")
    def registration(self):
        if self.sensorId is None and self.qrToken is None:
            raise ValueError("sensor or QR required")
        return self


class Detach(VehicleNumber):
    division: Literal["SENSOR", "QR"]


class PriceChange(VehicleNumber):
    priceType: Literal["BASIC", "PREMIUM"]
    priceInfo: Money | None = None

    @model_validator(mode="after")
    def amount(self):
        if (self.priceType == "PREMIUM") != (self.priceInfo is not None):
            raise ValueError("priceInfo required only for PREMIUM")
        return self


class Qr(Body):
    qrCode: SecretStr = Field(min_length=1, max_length=4096)


class Repair(VehicleNumber):
    date: Date
    reason: Reason | None = None


class Move(VehicleNumber):
    spotCode: Spot


class BookingAction(Body):
    bookedNo: Annotated[str, Field(min_length=3, max_length=52, pattern=r"^BO.+$")]
    action: Literal["APPROVE", "REJECT", "CANCEL"]
    reason: Reason | None = None


class ReservationCancel(Body):
    reservationId: Annotated[str, Field(min_length=1, max_length=50)]
    reason: Reason | None = None


class NadriLogin(Body):
    UID: Uid
    fcmToken: Token | None = None


class NadriProfile(Body):
    NAME: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    Age: Annotated[int, Field(strict=True, ge=0, le=150)] | None = None
    GENDER: Literal["M", "F", "OTHER"] | None = None
    NATIONALITY: Annotated[str, Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")] | None = None
    fcmToken: Token | None = None


class NadriAvailability(Body):
    startDate: Date
    returnDate: Date
    cc: Annotated[int, Field(strict=True, gt=0, le=2147483647)]
    deliveryRequested: StrictBool
    pickupLocation: Address | None = None
    returnLocation: Address | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.returnDate <= self.startDate or (self.returnDate - self.startDate).days > 42:
            raise ValueError("invalid rental date range")
        if self.deliveryRequested and not self.pickupLocation:
            raise ValueError("pickup location required")
        return self


class NadriRentalRequest(Body):
    spotMasterId: Identifier
    modelId: ModelId
    startDate: Date
    returnDate: Date
    totalPrice: Money
    currency: Currency
    deliveryRequested: StrictBool
    pickupLocation: Address | None = None
    returnLocation: Address | None = None

    @model_validator(mode="after")
    def dates_and_delivery(self):
        if self.returnDate <= self.startDate or (self.returnDate - self.startDate).days > 42:
            raise ValueError("invalid rental date range")
        if self.deliveryRequested and not self.pickupLocation:
            raise ValueError("pickup location required")
        return self


class NadriPaymentOrder(Body):
    reservationId: Annotated[str, Field(min_length=1, max_length=50)]


class NadriPaymentCapture(Body):
    paymentId: Positive


class RentApprove(Qr):
    bookedNo: Annotated[str, Field(min_length=3, max_length=52, pattern=r"^BO.+$")] | None = None
    uidToken: Identifier | None = None
    plannedEndDate: Date | None = None

    @model_validator(mode="after")
    def subject(self):
        if self.bookedNo:
            if self.uidToken is not None or self.plannedEndDate is not None:
                raise ValueError("reservation supplies uid token and end date")
        elif self.uidToken is None or self.plannedEndDate is None:
            raise ValueError("walk-in requires uid token and end date")
        return self


class TierRange(Body):
    minCc: Cc
    maxCc: Cc

    @model_validator(mode="after")
    def ordered(self):
        if self.minCc > self.maxCc:
            raise ValueError("invalid cc interval")
        return self


class TierCreate(TierRange):
    price: Money
    type: Literal["BASIC"]
    spotCode: Spot | None = None


class Delivery(Body):
    spotCode: Spot
    deliveryRegionId: Positive
    isDeliveryEnabled: StrictBool
    startDeliveryFee: Money
    returnDeliveryFee: Money
    memo: Annotated[str, Field(max_length=300)] | None = None

    @model_validator(mode="after")
    def same_fee(self):
        if self.startDeliveryFee != self.returnDeliveryFee:
            raise ValueError("MVP delivery and return unit fees must match")
        return self


class DeliveryDelete(Body):
    spotDeliveryRegionId: Positive
