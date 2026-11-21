"""Model -> JSON dict serializers shared by REST and WebSocket payloads."""
from .anpr.sources import split_credentials
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
        "phone": u.phone,
        "department": u.department,
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
        "rtsp_url": split_credentials(c.rtsp_url)[0],  # never return a password embedded in the URL
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
        "row_id": c.row_id,
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
        "owner_user_id": v.owner_user_id,
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


# ------------------------------------------------------- office parking
def office_out(o) -> dict:
    return {
        "id": o.id, "name": o.name, "city": o.city, "address": o.address,
        "latitude": o.latitude, "longitude": o.longitude, "is_24h": o.is_24h,
        "open_time": o.open_time, "close_time": o.close_time, "is_active": o.is_active, "notes": o.notes,
        "floors": [{"id": f.id, "name": f.name, "level": f.level,
                    "zones": [{"id": z.id, "name": z.name} for z in f.zones]} for f in o.floors],
    }


def slot_out(s, state: str | None = None) -> dict:
    zone = s.zone
    return {
        "id": s.id, "office_id": s.office_id, "zone_id": s.zone_id, "code": s.code,
        "zone": zone.name if zone else None, "floor": zone.floor.name if zone else None,
        "floor_level": zone.floor.level if zone else None,
        "vehicle_type": s.vehicle_type, "is_ev": s.is_ev, "is_accessible": s.is_accessible,
        "is_visitor": s.is_visitor, "status": s.status, "assigned_user_id": s.assigned_user_id,
        "assigned_to": (s.assigned_user.full_name or s.assigned_user.username) if s.assigned_user else None,
        **({"state": state} if state else {}),
    }


def booking_out(b, include_qr: bool = False) -> dict:
    from .services.bookings import qr_payload

    slot = b.slot
    out = {
        "id": b.id, "code": b.code, "status": b.status,
        "office_id": b.office_id, "office_name": b.office.name if b.office else None,
        "slot_id": b.slot_id, "slot_code": b.slot_code,
        "floor": slot.zone.floor.name if slot and slot.zone else None, "zone": slot.zone.name if slot and slot.zone else None,
        "user_id": b.user_id, "user_name": (b.user.full_name or b.user.username) if b.user else None,
        "plate_number": b.plate_number, "vehicle_type": b.vehicle_type,
        "visitor_name": b.visitor_name, "visitor_phone": b.visitor_phone,
        "start_at": b.start_at, "end_at": b.end_at,
        "checked_in_at": b.checked_in_at, "checked_out_at": b.checked_out_at,
        "cancelled_at": b.cancelled_at, "cancel_reason": b.cancel_reason, "notes": b.notes,
        "created_at": b.created_at,
    }
    if include_qr:  # only for the booking's owner / staff: the token proves the QR is genuine
        out["qr"] = qr_payload(b)
    return out
