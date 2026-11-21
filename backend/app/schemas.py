"""Pydantic request schemas (validated input for the REST API)."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

RoleT = Literal["SUPER_ADMIN", "PARKING_MANAGER", "SECURITY_OPERATOR", "REPORT_VIEWER", "EMPLOYEE"]
DirectionT = Literal["ENTRY", "EXIT"]
VehicleTypeT = Literal["CAR", "TWO_WHEELER", "COMMERCIAL"]


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)  # anything except spaces, e.g. an email address
    email: EmailStr

    @field_validator("username")
    @classmethod
    def _no_spaces(cls, v: str) -> str:
        v = v.strip()
        if any(ch.isspace() for ch in v):
            raise ValueError("Username cannot contain spaces")
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        return v
    full_name: str = Field("", max_length=128)
    password: str = Field(max_length=256)
    role: RoleT = "REPORT_VIEWER"
    is_active: bool = True


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(None, max_length=128)
    role: RoleT | None = None
    is_active: bool | None = None
    password: str | None = Field(None, max_length=256)


class DetectionZone(BaseModel):
    polygon: list[list[float]] = Field(min_length=3)
    trigger_line: float = Field(0.62, ge=0.0, le=1.0)

    @field_validator("polygon")
    @classmethod
    def check_points(cls, v):
        for p in v:
            if len(p) != 2 or not all(0.0 <= c <= 1.0 for c in p):
                raise ValueError("polygon points must be [x, y] normalised to 0..1")
        return v


class CameraBase(BaseModel):
    camera_code: str = Field("", max_length=32)  # empty: generated (CAM-EN-01, CAM-A-EX-01, ...)
    name: str = Field(min_length=1, max_length=128)
    ip_address: str = Field("", max_length=64)
    port: int = Field(554, ge=1, le=65535)
    onvif_port: int = Field(80, ge=1, le=65535)
    rtsp_url: str = Field("", max_length=512)
    username: str = Field("", max_length=128)
    password: str | None = Field(None, max_length=256)
    location: str = Field("", max_length=255)
    direction: DirectionT
    is_simulated: bool = False
    is_enabled: bool = True
    detection_zone: DetectionZone | None = None
    cooldown_seconds: int = Field(60, ge=0, le=3600)
    min_plate_confidence: float = Field(0.6, ge=0.0, le=1.0)
    sim_vehicles_per_minute: float = Field(4.0, gt=0, le=60)
    row_id: int | None = None  # None: main gate camera; set: camera at the entrance of a parking row


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    camera_code: str | None = Field(None, max_length=32)
    name: str | None = Field(None, max_length=128)
    ip_address: str | None = Field(None, max_length=64)
    port: int | None = None
    onvif_port: int | None = None
    rtsp_url: str | None = Field(None, max_length=512)
    username: str | None = Field(None, max_length=128)
    password: str | None = Field(None, max_length=256)
    location: str | None = Field(None, max_length=255)
    direction: DirectionT | None = None
    is_simulated: bool | None = None
    is_enabled: bool | None = None
    detection_zone: DetectionZone | None = None
    cooldown_seconds: int | None = Field(None, ge=0, le=3600)
    min_plate_confidence: float | None = Field(None, ge=0.0, le=1.0)
    sim_vehicles_per_minute: float | None = Field(None, gt=0, le=60)
    row_id: int | None = None


class OnvifProbeIn(BaseModel):
    ip_address: str = Field(max_length=64)
    onvif_port: int = 80
    username: str = Field("", max_length=128)
    password: str = Field("", max_length=256)


class TestStreamIn(BaseModel):
    rtsp_url: str = Field(max_length=512)
    username: str = Field("", max_length=128)
    password: str = Field("", max_length=256)
    camera_id: int | None = None  # when editing: use the saved password if none is typed


def _not_future(v: datetime | None) -> datetime | None:
    if v is not None:
        aware = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if aware > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("Time cannot be in the future")
    return v


class ManualEntryIn(BaseModel):
    plate_number: str = Field(max_length=32)
    vehicle_type: VehicleTypeT = "CAR"
    timestamp: datetime | None = None
    camera_id: int | None = None
    notes: str = Field("", max_length=2000)

    @field_validator("timestamp")
    @classmethod
    def _not_in_future(cls, v):
        return _not_future(v)


class ManualExitIn(BaseModel):
    plate_number: str | None = Field(None, max_length=32)
    session_id: int | None = None
    timestamp: datetime | None = None
    notes: str = Field("", max_length=2000)

    @field_validator("timestamp")
    @classmethod
    def _not_in_future(cls, v):
        return _not_future(v)


class CancelIn(BaseModel):
    reason: str = Field(min_length=3)


class ResolveExitIn(BaseModel):
    session_id: int


class CorrectPlateIn(BaseModel):
    plate_number: str = Field(max_length=32)


class ReviewIn(BaseModel):
    corrected_plate: str | None = Field(None, max_length=32)
    vehicle_type: VehicleTypeT | None = None


class VehicleUpdate(BaseModel):
    vehicle_type: VehicleTypeT | None = None
    is_reserved: bool | None = None
    is_blacklisted: bool | None = None
    owner_name: str | None = Field(None, max_length=128)
    notes: str | None = Field(None, max_length=2000)


class VehicleCreate(BaseModel):
    plate_number: str = Field(max_length=32)
    vehicle_type: VehicleTypeT = "CAR"
    is_reserved: bool = False
    is_blacklisted: bool = False
    owner_name: str = Field("", max_length=128)
    notes: str = Field("", max_length=2000)


class CapacityUpdate(BaseModel):
    total_capacity: int | None = Field(None, ge=0, le=100000)
    alert_threshold_pct: int | None = Field(None, ge=1, le=100)
    label: str | None = Field(None, max_length=64)
    is_active: bool | None = None


class SimulateDetectionIn(BaseModel):
    """Inject a single detection into a camera's pipeline (testing tool)."""
    camera_id: int
    plate_number: str | None = Field(None, max_length=32)
    plate_confidence: float = Field(0.92, ge=0, le=1)
    vehicle_type: VehicleTypeT = "CAR"


class RowIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    capacity: int = Field(ge=0, le=100000)
    sort_order: int = 0
    is_active: bool = True


class RowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    capacity: int | None = Field(None, ge=0, le=100000)
    sort_order: int | None = None
    is_active: bool | None = None


class RowCountIn(BaseModel):
    count: int = Field(ge=0, le=100000)
    reason: str = Field("", max_length=255)


# ------------------------------------------------------- office parking
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class OfficeIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    city: str = Field("", max_length=64)
    address: str = Field("", max_length=255)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    is_24h: bool = False
    open_time: str = Field("07:00", pattern=HHMM)
    close_time: str = Field("22:00", pattern=HHMM)
    is_active: bool = True
    notes: str = Field("", max_length=2000)


class OfficeUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=128)
    city: str | None = Field(None, max_length=64)
    address: str | None = Field(None, max_length=255)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    is_24h: bool | None = None
    open_time: str | None = Field(None, pattern=HHMM)
    close_time: str | None = Field(None, pattern=HHMM)
    is_active: bool | None = None
    notes: str | None = Field(None, max_length=2000)


class FloorIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    level: int = Field(0, ge=-20, le=200)


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class SlotsBulkIn(BaseModel):
    """Create slots PREFIX + number, e.g. prefix "A-", start 1, count 20 -> A-01 ... A-20."""
    prefix: str = Field("", max_length=16)
    start: int = Field(1, ge=0, le=99999)
    count: int = Field(1, ge=1, le=500)
    digits: int = Field(2, ge=1, le=5)
    vehicle_type: VehicleTypeT = "CAR"
    is_ev: bool = False
    is_accessible: bool = False
    is_visitor: bool = False


class SlotUpdate(BaseModel):
    code: str | None = Field(None, min_length=1, max_length=32)
    vehicle_type: VehicleTypeT | None = None
    is_ev: bool | None = None
    is_accessible: bool | None = None
    is_visitor: bool | None = None
    status: Literal["ACTIVE", "OUT_OF_SERVICE"] | None = None
    assigned_user_id: int | None = None
    zone_id: int | None = None


class MyVehicleIn(BaseModel):
    plate_number: str = Field(min_length=3, max_length=32)
    vehicle_type: VehicleTypeT = "CAR"
    notes: str = Field("", max_length=200)


class VisitorIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    plate_number: str = Field(min_length=3, max_length=32)
    vehicle_type: VehicleTypeT = "CAR"
    phone: str = Field("", max_length=32)


class BookingIn(BaseModel):
    office_id: int
    start_at: datetime
    end_at: datetime
    vehicle_id: int | None = None
    slot_id: int | None = None
    visitor: VisitorIn | None = None
    prefer_ev: bool = False
    prefer_accessible: bool = False
    notes: str = Field("", max_length=500)
    user_id: int | None = None  # book for another person (bookings.manage)


class BookingChangeIn(BaseModel):
    start_at: datetime
    end_at: datetime


class BookingCancelIn(BaseModel):
    reason: str = Field("", max_length=255)


class ScanIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=128)
    email: EmailStr
    password: str = Field(max_length=256)
    phone: str = Field("", max_length=32)
    department: str = Field("", max_length=64)


class ProfileIn(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=128)
    phone: str | None = Field(None, max_length=32)
    department: str | None = Field(None, max_length=64)
