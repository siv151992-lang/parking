"""Model -> JSON dict serializers shared by REST and WebSocket payloads."""
from .models import (
    Camera,
    EntryTransaction,
    ExitTransaction,
    ParkingSession,
    User,
    Vehicle,
    VehicleDetection,
)
from .security import permissions_for


def media_url(path: str | None) -> str | None:
    return f"/api/media/{path}" if path else None


def user_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "last_login_at": u.last_login_at,
        "created_at": u.created_at,
        "permissions": permissions_for(u.role),
    }


def camera_out(c: Camera, runtime: dict | None = None) -> dict:
    return {
        "id": c.id,
        "camera_code": c.camera_code,
        "name": c.name,
        "ip_address": c.ip_address,
        "port": c.port,
        "onvif_port": c.onvif_port,
        "rtsp_url": c.rtsp_url,
        "username": c.username,
        "has_password": bool(c.password),
        "location": c.location,
        "direction": c.direction,
        "is_simulated": c.is_simulated,
        "is_enabled": c.is_enabled,
        "detection_zone": c.detection_zone,
        "cooldown_seconds": c.cooldown_seconds,
        "min_plate_confidence": c.min_plate_confidence,
        "sim_vehicles_per_minute": c.sim_vehicles_per_minute,
        "status": c.status,
        "last_seen_at": c.last_seen_at,
        "last_detection_at": c.last_detection_at,
        "last_error": c.last_error,
        "created_at": c.created_at,
        "runtime": runtime or {},
    }


def vehicle_out(v: Vehicle) -> dict:
    return {
        "id": v.id,
        "plate_number": v.plate_number,
        "vehicle_type": v.vehicle_type,
        "is_reserved": v.is_reserved,
        "is_blacklisted": v.is_blacklisted,
        "owner_name": v.owner_name,
        "notes": v.notes,
        "first_seen_at": v.first_seen_at,
        "last_seen_at": v.last_seen_at,
        "total_visits": v.total_visits,
    }


def detection_out(d: VehicleDetection) -> dict:
    return {
        "id": d.id,
        "camera_id": d.camera_id,
        "camera_name": d.camera.name if d.camera else "Manual",
        "direction": d.direction,
        "plate_number": d.plate_number,
        "raw_plate_text": d.raw_plate_text,
        "plate_confidence": round(d.plate_confidence or 0, 3),
        "vehicle_type": d.vehicle_type,
        "vehicle_confidence": round(d.vehicle_confidence or 0, 3),
        "track_id": d.track_id,
        "ocr_reads": d.ocr_reads,
        "vehicle_image": media_url(d.vehicle_image_path),
        "plate_image": media_url(d.plate_image_path),
        "is_simulated": d.is_simulated,
        "status": d.status,
        "status_reason": d.status_reason,
        "needs_review": d.needs_review,
        "corrected_plate": d.corrected_plate,
        "reviewed_at": d.reviewed_at,
        "detected_at": d.detected_at,
    }


def session_out(s: ParkingSession) -> dict:
    return {
        "id": s.id,
        "vehicle_id": s.vehicle_id,
        "plate_number": s.plate_number,
        "vehicle_type": s.vehicle_type,
        "category": s.category,
        "status": s.status,
        "entry_time": s.entry_time,
        "exit_time": s.exit_time,
        "duration_seconds": s.duration_seconds,
        "entry_camera": s.entry_camera.name if s.entry_camera else None,
        "exit_camera": s.exit_camera.name if s.exit_camera else None,
        "entry_camera_id": s.entry_camera_id,
        "exit_camera_id": s.exit_camera_id,
        "entry_confidence": round(s.entry_confidence or 0, 3),
        "exit_confidence": round(s.exit_confidence, 3) if s.exit_confidence is not None else None,
        "entry_vehicle_image": media_url(s.entry_vehicle_image),
        "entry_plate_image": media_url(s.entry_plate_image),
        "exit_vehicle_image": media_url(s.exit_vehicle_image),
        "exit_plate_image": media_url(s.exit_plate_image),
        "needs_review": s.needs_review,
        "is_simulated": s.is_simulated,
        "notes": s.notes,
    }


def entry_out(t: EntryTransaction) -> dict:
    return {
        "id": t.id,
        "session_id": t.session_id,
        "camera_id": t.camera_id,
        "camera_name": t.camera.name if t.camera else "Manual",
        "detection_id": t.detection_id,
        "plate_number": t.plate_number,
        "vehicle_type": t.vehicle_type,
        "category": t.category,
        "confidence": round(t.confidence or 0, 3),
        "timestamp": t.timestamp,
        "source": t.source,
        "status": t.status,
        "notes": t.notes,
    }


def exit_out(t: ExitTransaction) -> dict:
    return {
        "id": t.id,
        "session_id": t.session_id,
        "camera_id": t.camera_id,
        "camera_name": t.camera.name if t.camera else ("System" if t.source == "SYSTEM" else "Manual"),
        "detection_id": t.detection_id,
        "plate_number": t.plate_number,
        "vehicle_type": t.vehicle_type,
        "confidence": round(t.confidence or 0, 3),
        "timestamp": t.timestamp,
        "source": t.source,
        "status": t.status,
        "notes": t.notes,
    }
