"""Customer/admin commands for the approved one-form handover flow."""
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.rental_inputs import Address
from app.rental_profile import DocumentNumber, SnsInfo
from app.schemas import Body, Identifier

RequestKey = Annotated[str, Field(min_length=16, max_length=64, pattern=r"^[a-z0-9_-]+$")]
HelmetCount = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
MediaKind = Literal["VEHICLE_VIDEO", "PASSPORT_PHOTO", "DRIVER_LICENSE_PHOTO", "EXTRA_PHOTO"]


class StartHandover(Body):
    clientRequestId: RequestKey


class EmptyCommand(Body):
    pass


class FormPatch(Body):
    passportNumber: DocumentNumber | None = None
    driverLicenseNumber: DocumentNumber | None = None
    accommodationLocation: Address | None = None
    helmetCount: HelmetCount | None = None
    snsInfo: SnsInfo | None = None

    @model_validator(mode="after")
    def supplied(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Supply at least one non-null form field")
        return self


class ClaimHandover(Body):
    trigger: Literal["PHOTO_CAPTURE_STARTED", "REVIEW_WITHOUT_PHOTOS"]


class ReviewHandover(Body):
    action: Literal["CONFIRM", "PROPOSE_CHANGES"]
    changes: FormPatch | None = None
    reason: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    skipPhotoKinds: list[Literal["PASSPORT_PHOTO", "DRIVER_LICENSE_PHOTO"]] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def proposal(self):
        if (self.action == "PROPOSE_CHANGES") != (self.changes is not None):
            raise ValueError("Only PROPOSE_CHANGES accepts and requires changes")
        if self.action == "PROPOSE_CHANGES" and not self.reason:
            raise ValueError("A change proposal requires a reason")
        return self


class RespondHandover(Body):
    decision: Literal["ACCEPT", "REJECT"]


class PrepareMedia(Body):
    clientFileId: RequestKey
    kind: MediaKind
    contentType: Literal["video/mp4", "image/jpeg", "image/png", "image/webp"]
    sizeBytes: Annotated[int, Field(strict=True, ge=1, le=52428800)]


class UntrackedRent(Body):
    vehicleNumber: Annotated[str, Field(min_length=1, max_length=25, pattern=r"\S")]
    action: Literal["START", "END"]
    endDate: date | None = None

    @model_validator(mode="after")
    def period(self):
        if self.action == "START" and self.endDate is None:
            raise ValueError("START requires endDate")
        return self


class ReplaceVehicle(Body):
    vehicleId: Identifier
    expectedVehicleId: Identifier
    expectedUpdatedAt: Annotated[str, Field(min_length=1, max_length=50)]
    reason: Annotated[str, Field(min_length=1, max_length=200)]
