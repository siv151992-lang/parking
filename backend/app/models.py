"""Database models (PostgreSQL schema).

Tables: users, cameras, vehicles, vehicle_detections, parking_sessions,
entry_transactions, exit_transactions, parking_capacity, alerts, audit_logs,
system_settings.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---- Enumerations (stored as strings for portable, migration-friendly schema) ----
class Role:
    SUPER_ADMIN = "SUPER_ADMIN"
    PARKING_MANAGER = "PARKING_MANAGER"
    SECURITY_OPERATOR = "SECURITY_OPERATOR"
    REPORT_VIEWER = "REPORT_VIEWER"
    ALL = [SUPER_ADMIN, PARKING_MANAGER, SECURITY_OPERATOR, REPORT_VIEWER]


class Direction:
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class CameraStatus:
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    CONNECTING = "CONNECTING"
    DISABLED = "DISABLED"


class VehicleType:
    CAR = "CAR"
    TWO_WHEELER = "TWO_WHEELER"
    COMMERCIAL = "COMMERCIAL"  # bus / truck / heavy
    ALL = [CAR, TWO_WHEELER, COMMERCIAL]


class ParkingCategory:
    CAR = "CAR"
    TWO_WHEELER = "TWO_WHEELER"
    HEAVY = "HEAVY"
    RESERVED = "RESERVED"
    ALL = [CAR, TWO_WHEELER, HEAVY, RESERVED]
    LABELS = {
        CAR: "Car Parking",
        TWO_WHEELER: "Two-Wheeler Parking",
        HEAVY: "Heavy Vehicle Parking",
        RESERVED: "Reserved Parking",
    }


VEHICLE_TYPE_TO_CATEGORY = {
    VehicleType.CAR: ParkingCategory.CAR,
    VehicleType.TWO_WHEELER: ParkingCategory.TWO_WHEELER,
    VehicleType.COMMERCIAL: ParkingCategory.HEAVY,
}


class SessionStatus:
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DetectionStatus:
    ENTRY_CREATED = "ENTRY_CREATED"
    EXIT_RECORDED = "EXIT_RECORDED"
    DUPLICATE = "DUPLICATE"
    COOLDOWN = "COOLDOWN"
    FAILED_OCR = "FAILED_OCR"
    REJECTED = "REJECTED"


class TxSource:
    ANPR = "ANPR"
    SIMULATED = "SIMULATED"
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"


class EntryStatus:
    VALID = "VALID"
    CANCELLED = "CANCELLED"


class ExitStatus:
    MATCHED = "MATCHED"            # exact plate match to an active session
    FUZZY_MATCHED = "FUZZY_MATCHED"  # matched allowing OCR confusion / 1 char edit
    UNREAD_MATCHED = "UNREAD_MATCHED"  # unreadable plate matched to oldest unread session
    MANUAL_MATCHED = "MANUAL_MATCHED"  # operator linked it to a session
    AUTO_CLOSED = "AUTO_CLOSED"    # missed exit closed by the system on re-entry
    UNMATCHED = "UNMATCHED"        # no session found: does NOT decrement occupancy
    CANCELLED = "CANCELLED"
    COUNTED = (MATCHED, FUZZY_MATCHED, UNREAD_MATCHED, MANUAL_MATCHED, AUTO_CLOSED)


class AlertType:
    CAMERA_OFFLINE = "CAMERA_OFFLINE"
    CAMERA_ONLINE = "CAMERA_ONLINE"
    CAPACITY_WARNING = "CAPACITY_WARNING"
    CAPACITY_FULL = "CAPACITY_FULL"
    OCR_FAILED = "OCR_FAILED"
    DUPLICATE_DETECTION = "DUPLICATE_DETECTION"
    UNMATCHED_EXIT = "UNMATCHED_EXIT"
    SUSPICIOUS_VEHICLE = "SUSPICIOUS_VEHICLE"
    COUNT_MISMATCH = "COUNT_MISMATCH"


class Severity:
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# ------------------------------------------------------------------ users
class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=Role.REPORT_VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- cameras
class Camera(TimestampMixin, Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=554, nullable=False)
    onvif_port: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    rtsp_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    username: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    password: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Detection zone: {"polygon": [[x,y],...normalised 0-1], "trigger_line": 0.6}
    detection_zone: Mapped[dict | None] = mapped_column(JSONType)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    min_plate_confidence: Mapped[float] = mapped_column(Float, default=0.6, nullable=False)
    sim_vehicles_per_minute: Mapped[float] = mapped_column(Float, default=4.0, nullable=False)

    status: Mapped[str] = mapped_column(String(16), default=CameraStatus.OFFLINE, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_detection_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------- vehicles
class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    vehicle_type: Mapped[str] = mapped_column(String(16), default=VehicleType.CAR, nullable=False)
    is_reserved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    owner_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_visits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# ----------------------------------------------------- vehicle_detections
class VehicleDetection(Base):
    __tablename__ = "vehicle_detections"
    __table_args__ = (
        Index("ix_detections_camera_time", "camera_id", "detected_at"),
        Index("ix_detections_plate_time", "plate_number", "detected_at"),
        Index("ix_detections_review", "needs_review"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    plate_number: Mapped[str | None] = mapped_column(String(20))
    raw_plate_text: Mapped[str | None] = mapped_column(String(64))
    plate_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(16), default=VehicleType.CAR, nullable=False)
    vehicle_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    track_id: Mapped[str | None] = mapped_column(String(64))
    ocr_reads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    vehicle_image_path: Mapped[str | None] = mapped_column(String(255))
    plate_image_path: Mapped[str | None] = mapped_column(String(255))
    bbox: Mapped[list | None] = mapped_column(JSONType)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    status_reason: Mapped[str | None] = mapped_column(String(255))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    corrected_plate: Mapped[str | None] = mapped_column(String(20))
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    camera = relationship("Camera", lazy="selectin")


# ------------------------------------------------------- parking_sessions
class ParkingSession(TimestampMixin, Base):
    __tablename__ = "parking_sessions"
    __table_args__ = (
        # Hard guarantee: one ACTIVE session per plate (prevents duplicate entries
        # even if two entry cameras fire simultaneously).
        Index(
            "uq_active_session_per_plate",
            "plate_number",
            unique=True,
            postgresql_where=text("status = 'ACTIVE' AND plate_number IS NOT NULL"),
            sqlite_where=text("status = 'ACTIVE' AND plate_number IS NOT NULL"),
        ),
        Index("ix_sessions_status_category", "status", "category"),
        Index("ix_sessions_entry_time", "entry_time"),
        Index("ix_sessions_exit_time", "exit_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), index=True)
    plate_number: Mapped[str | None] = mapped_column(String(20))
    vehicle_type: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=SessionStatus.ACTIVE, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    entry_camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    exit_camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    entry_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    exit_confidence: Mapped[float | None] = mapped_column(Float)
    entry_vehicle_image: Mapped[str | None] = mapped_column(String(255))
    entry_plate_image: Mapped[str | None] = mapped_column(String(255))
    exit_vehicle_image: Mapped[str | None] = mapped_column(String(255))
    exit_plate_image: Mapped[str | None] = mapped_column(String(255))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    entry_camera = relationship("Camera", foreign_keys=[entry_camera_id], lazy="selectin")
    exit_camera = relationship("Camera", foreign_keys=[exit_camera_id], lazy="selectin")


# ----------------------------------------------------- entry_transactions
class EntryTransaction(Base):
    __tablename__ = "entry_transactions"
    __table_args__ = (Index("ix_entry_tx_time_status", "timestamp", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("parking_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"), index=True)
    detection_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_detections.id", ondelete="SET NULL"))
    plate_number: Mapped[str | None] = mapped_column(String(20), index=True)
    vehicle_type: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=EntryStatus.VALID, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    camera = relationship("Camera", lazy="selectin")


# ------------------------------------------------------ exit_transactions
class ExitTransaction(Base):
    __tablename__ = "exit_transactions"
    __table_args__ = (Index("ix_exit_tx_time_status", "timestamp", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("parking_sessions.id", ondelete="SET NULL"), index=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"), index=True)
    detection_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_detections.id", ondelete="SET NULL"))
    plate_number: Mapped[str | None] = mapped_column(String(20), index=True)
    vehicle_type: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    camera = relationship("Camera", lazy="selectin")


# ------------------------------------------------------- parking_capacity
class ParkingCapacity(TimestampMixin, Base):
    __tablename__ = "parking_capacity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    total_capacity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    alert_threshold_pct: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # NORMAL / WARNING / FULL: last alert level raised, prevents alert spam
    alert_state: Mapped[str] = mapped_column(String(10), default="NORMAL", nullable=False)


# ----------------------------------------------------------------- alerts
class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_created", "created_at"),
        Index("ix_alerts_type_resolved", "alert_type", "is_resolved"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default=Severity.INFO, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    session_id: Mapped[int | None] = mapped_column(ForeignKey("parking_sessions.id", ondelete="SET NULL"))
    detection_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_detections.id", ondelete="SET NULL"))
    plate_number: Mapped[str | None] = mapped_column(String(20))
    data: Mapped[dict | None] = mapped_column(JSONType)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ------------------------------------------------------------- audit_logs
class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    username: Mapped[str] = mapped_column(String(64), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JSONType)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# -------------------------------------------------------- system_settings
class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
