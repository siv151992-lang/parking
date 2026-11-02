"""Vehicle counting engine.

Every ANPR event (real or simulated) and every manual correction goes through
this module, which is the only code allowed to open/close parking sessions.

Duplicate prevention is layered:
  1. Tracker (anpr/tracker.py) - one event per physical vehicle track, fired
     only when the vehicle crosses the trigger line inside the detection zone.
  2. Plate voting - OCR reads across the track's frames are aggregated.
  3. Cooldown - the same plate on the same direction within the camera's
     cooldown window is recorded as COOLDOWN and ignored (covers multiple
     cameras watching the same lane).
  4. Transaction validation - an ENTRY for a plate that already has an ACTIVE
     session is a DUPLICATE; EXITs only count when they close a session.
  5. Database constraint - a partial unique index allows only one ACTIVE
     session per plate, even across processes.

Vehicles inside == number of ACTIVE sessions == valid entries - counted exits.
"""
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    VEHICLE_TYPE_TO_CATEGORY,
    AlertType,
    Camera,
    DetectionStatus,
    Direction,
    EntryStatus,
    EntryTransaction,
    ExitStatus,
    ExitTransaction,
    ParkingCategory,
    ParkingSession,
    SessionStatus,
    Severity,
    TxSource,
    User,
    Vehicle,
    VehicleDetection,
    VehicleType,
)
from ..serializers import detection_out, entry_out, exit_out, session_out
from . import events, settings_store
from .alerts import create_alert
from .audit import audit
from .media import save_image
from .occupancy import check_capacity_alerts, emit_occupancy
from .plates import is_valid_plate, normalize_plate, plate_distance
from .timeutil import ensure_aware, utcnow

log = logging.getLogger("counting")

# Serialises all counting decisions inside this process so that two cameras
# firing at the same instant cannot both decide "no active session".
_lock = threading.RLock()


class CountingError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class DetectionEvent:
    plate_text: str | None
    plate_confidence: float
    vehicle_type: str = VehicleType.CAR
    vehicle_confidence: float = 0.0
    timestamp: datetime = field(default_factory=utcnow)
    direction: str | None = None  # defaults to the camera's direction
    track_id: str | None = None
    ocr_reads: int = 0
    vehicle_image: np.ndarray | None = None
    plate_image: np.ndarray | None = None
    bbox: list | None = None
    is_simulated: bool = False


def category_for(vehicle_type: str, vehicle: Vehicle | None) -> str:
    if vehicle is not None and vehicle.is_reserved:
        return ParkingCategory.RESERVED
    return VEHICLE_TYPE_TO_CATEGORY.get(vehicle_type, ParkingCategory.CAR)


# ------------------------------------------------------------------ helpers
def _find_vehicle(db: Session, plate: str | None) -> Vehicle | None:
    if not plate:
        return None
    return db.query(Vehicle).filter(Vehicle.plate_number == plate).first()


def _touch_vehicle(db: Session, plate: str, vehicle_type: str, ts: datetime, new_visit: bool) -> Vehicle:
    v = _find_vehicle(db, plate)
    if v is None:
        v = Vehicle(plate_number=plate, vehicle_type=vehicle_type, first_seen_at=ts, total_visits=0)
        db.add(v)
    v.vehicle_type = vehicle_type or v.vehicle_type
    v.last_seen_at = ts
    if new_visit:
        v.total_visits += 1
    db.flush()
    return v


def _active_session(db: Session, plate: str) -> ParkingSession | None:
    return (
        db.query(ParkingSession)
        .filter(ParkingSession.plate_number == plate, ParkingSession.status == SessionStatus.ACTIVE)
        .with_for_update()
        .first()
    )


def _record_detection(db, camera, ev, direction, plate, status, reason=None, needs_review=False,
                      vehicle=None, save_images=True) -> VehicleDetection:
    det = VehicleDetection(
        camera_id=camera.id if camera else None,
        vehicle_id=vehicle.id if vehicle else None,
        direction=direction,
        plate_number=plate,
        raw_plate_text=(ev.plate_text or None) and ev.plate_text[:64],
        plate_confidence=float(ev.plate_confidence or 0),
        vehicle_type=ev.vehicle_type,
        vehicle_confidence=float(ev.vehicle_confidence or 0),
        track_id=ev.track_id,
        ocr_reads=ev.ocr_reads,
        vehicle_image_path=save_image(ev.vehicle_image, "vehicle") if save_images else None,
        plate_image_path=save_image(ev.plate_image, "plate") if save_images else None,
        bbox=ev.bbox,
        is_simulated=ev.is_simulated,
        status=status,
        status_reason=reason,
        needs_review=needs_review,
        detected_at=ev.timestamp,
    )
    db.add(det)
    db.flush()
    if camera:
        camera.last_detection_at = ev.timestamp
    events.emit(db, "detection", detection_out(det))
    return det


def _close_session(db, session, ts, *, camera=None, detection=None, status=ExitStatus.MATCHED,
                   source=TxSource.ANPR, plate=None, confidence=None, user=None, notes="") -> ExitTransaction:
    session.status = SessionStatus.CLOSED
    session.exit_time = ts
    session.duration_seconds = max(0, int((ts - ensure_aware(session.entry_time)).total_seconds()))
    session.exit_camera_id = camera.id if camera else None
    session.exit_confidence = confidence
    if detection is not None:
        session.exit_vehicle_image = detection.vehicle_image_path
        session.exit_plate_image = detection.plate_image_path
    if status in (ExitStatus.FUZZY_MATCHED, ExitStatus.UNREAD_MATCHED, ExitStatus.AUTO_CLOSED):
        session.needs_review = True
    tx = ExitTransaction(
        session_id=session.id,
        camera_id=camera.id if camera else None,
        detection_id=detection.id if detection else None,
        plate_number=plate or session.plate_number,
        vehicle_type=session.vehicle_type,
        confidence=confidence or 0.0,
        timestamp=ts,
        source=source,
        status=status,
        created_by_id=user.id if user else None,
        notes=notes,
    )
    db.add(tx)
    db.flush()
    events.emit(db, "exit", {**exit_out(tx), "session": session_out(session)})
    return tx


def _open_session(db, *, plate, vehicle, vehicle_type, ts, camera, detection, confidence, source,
                  is_simulated, user=None, notes="", needs_review=False) -> tuple[ParkingSession, EntryTransaction]:
    category = category_for(vehicle_type, vehicle)
    session = ParkingSession(
        vehicle_id=vehicle.id if vehicle else None,
        plate_number=plate,
        vehicle_type=vehicle_type,
        category=category,
        status=SessionStatus.ACTIVE,
        entry_time=ts,
        entry_camera_id=camera.id if camera else None,
        entry_confidence=confidence,
        entry_vehicle_image=detection.vehicle_image_path if detection else None,
        entry_plate_image=detection.plate_image_path if detection else None,
        needs_review=needs_review,
        is_simulated=is_simulated,
        notes=notes,
    )
    nested = db.begin_nested()
    try:
        db.add(session)
        db.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()
        raise CountingError(f"Vehicle {plate} already has an active parking session", 409)
    tx = EntryTransaction(
        session_id=session.id,
        camera_id=camera.id if camera else None,
        detection_id=detection.id if detection else None,
        plate_number=plate,
        vehicle_type=vehicle_type,
        category=category,
        confidence=confidence,
        timestamp=ts,
        source=source,
        status=EntryStatus.VALID,
        created_by_id=user.id if user else None,
        notes=notes,
    )
    db.add(tx)
    db.flush()
    events.emit(db, "entry", {**entry_out(tx), "session": session_out(session)})
    return session, tx


def _suspicious_checks(db, cfg, plate, vehicle, camera, ev):
    if vehicle is not None and vehicle.is_blacklisted:
        create_alert(
            db, AlertType.SUSPICIOUS_VEHICLE, Severity.CRITICAL,
            f"Blacklisted vehicle {plate} detected",
            f"Blacklisted vehicle detected at {camera.name if camera else 'manual entry'}. {vehicle.notes}".strip(),
            camera_id=camera.id if camera else None, plate_number=plate, is_simulated=ev.is_simulated,
            data={"reason": "blacklisted"},
        )
    window = int(cfg["suspicious_window_minutes"])
    limit = int(cfg["suspicious_repeat_entries"])
    if limit > 0:
        n = (
            db.query(func.count(EntryTransaction.id))
            .filter(EntryTransaction.plate_number == plate, EntryTransaction.timestamp >= ev.timestamp - timedelta(minutes=window))
            .scalar()
        )
        if n + 1 >= limit:
            create_alert(
                db, AlertType.SUSPICIOUS_VEHICLE, Severity.WARNING,
                f"Repeated entries by {plate}",
                f"{n + 1} entries within {window} minutes.",
                camera_id=camera.id if camera else None, plate_number=plate, is_simulated=ev.is_simulated,
                data={"reason": "repeated_entries", "count": n + 1}, dedupe_seconds=window * 60,
            )


def _find_exit_match(db, cfg, plate, plate_ok, vehicle_type):
    """Return (session, method) for an exit event."""
    if plate_ok:
        s = _active_session(db, plate)
        if s:
            return s, ExitStatus.MATCHED
        if cfg["fuzzy_match_enabled"]:
            max_d = int(cfg["fuzzy_max_distance"])
            candidates = (
                db.query(ParkingSession)
                .filter(ParkingSession.status == SessionStatus.ACTIVE, ParkingSession.plate_number.isnot(None))
                .all()
            )
            scored = [(plate_distance(plate, c.plate_number), c) for c in candidates if abs(len(c.plate_number) - len(plate)) <= max_d]
            scored = [x for x in scored if x[0] <= max_d]
            if scored:
                best = min(d for d, _ in scored)
                best_list = [c for d, c in scored if d == best]
                if len(best_list) == 1:  # only accept unambiguous fuzzy matches
                    return best_list[0], ExitStatus.FUZZY_MATCHED
    if cfg["unread_exit_matching"]:
        category = VEHICLE_TYPE_TO_CATEGORY.get(vehicle_type, ParkingCategory.CAR)
        base = db.query(ParkingSession).filter(
            ParkingSession.status == SessionStatus.ACTIVE, ParkingSession.plate_number.is_(None)
        )
        s = base.filter(ParkingSession.category == category).order_by(ParkingSession.entry_time).with_for_update().first()
        if s is None and not plate_ok:
            s = base.order_by(ParkingSession.entry_time).with_for_update().first()
        if s:
            return s, ExitStatus.UNREAD_MATCHED
    return None, None


# --------------------------------------------------------- public: ANPR flow
def process_detection(db: Session, camera_id: int | None, ev: DetectionEvent) -> dict:
    """Process one vehicle pass from an ANPR camera (or simulator)."""
    with _lock:
        try:
            result = _process(db, camera_id, ev)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise


def _process(db: Session, camera_id: int | None, ev: DetectionEvent) -> dict:
    cfg = settings_store.get_all(db)
    camera = db.get(Camera, camera_id) if camera_id else None
    direction = ev.direction or (camera.direction if camera else Direction.ENTRY)
    ev.timestamp = ensure_aware(ev.timestamp)
    ev.vehicle_type = ev.vehicle_type if ev.vehicle_type in VehicleType.ALL else VehicleType.CAR
    plate = normalize_plate(ev.plate_text)
    min_conf = camera.min_plate_confidence if camera else 0.0
    format_ok = is_valid_plate(plate, int(cfg["min_plate_length"]), int(cfg["max_plate_length"]), cfg["plate_regex"])
    plate_ok = format_ok and ev.plate_confidence >= min_conf
    low_conf_text = plate if (format_ok and not plate_ok) else None
    stored_plate = plate if plate_ok else None
    source = TxSource.SIMULATED if ev.is_simulated else TxSource.ANPR

    # ---- Layer 3: cooldown (same plate, same direction, any camera)
    if plate_ok and camera and camera.cooldown_seconds > 0:
        recent = (
            db.query(VehicleDetection.id)
            .filter(
                VehicleDetection.plate_number == plate,
                VehicleDetection.direction == direction,
                VehicleDetection.status.in_([DetectionStatus.ENTRY_CREATED, DetectionStatus.EXIT_RECORDED, DetectionStatus.DUPLICATE]),
                VehicleDetection.detected_at >= ev.timestamp - timedelta(seconds=camera.cooldown_seconds),
            )
            .first()
        )
        if recent:
            det = _record_detection(db, camera, ev, direction, plate, DetectionStatus.COOLDOWN,
                                    f"Seen within {camera.cooldown_seconds}s cooldown", save_images=False)
            return {"status": DetectionStatus.COOLDOWN, "detection_id": det.id, "plate": plate}

    if direction == Direction.ENTRY:
        return _process_entry(db, cfg, camera, ev, direction, stored_plate, plate_ok, low_conf_text, source)
    return _process_exit(db, cfg, camera, ev, direction, stored_plate, plate_ok, low_conf_text, source)


def _process_entry(db, cfg, camera, ev, direction, plate, plate_ok, low_conf_text, source):
    vehicle = _find_vehicle(db, plate) if plate_ok else None

    # ---- Layer 4: transaction validation
    if plate_ok:
        active = _active_session(db, plate)
        if active:
            age_min = (ev.timestamp - ensure_aware(active.entry_time)).total_seconds() / 60
            if age_min >= float(cfg["reentry_auto_close_minutes"]):
                # The vehicle must have left without the exit camera reading it.
                _close_session(db, active, ev.timestamp, status=ExitStatus.AUTO_CLOSED, source=TxSource.SYSTEM,
                               notes="Exit not detected; session auto-closed on re-entry")
            else:
                det = _record_detection(db, camera, ev, direction, plate, DetectionStatus.DUPLICATE,
                                        f"Active session #{active.id} already exists", vehicle=vehicle)
                if cfg["duplicate_alerts_enabled"]:
                    create_alert(
                        db, AlertType.DUPLICATE_DETECTION, Severity.WARNING,
                        f"Duplicate entry blocked: {plate}",
                        f"{plate} already inside since {ensure_aware(active.entry_time):%Y-%m-%d %H:%M} (session #{active.id}).",
                        camera_id=camera.id if camera else None, session_id=active.id, detection_id=det.id,
                        plate_number=plate, is_simulated=ev.is_simulated, dedupe_seconds=300,
                    )
                return {"status": DetectionStatus.DUPLICATE, "detection_id": det.id, "session_id": active.id, "plate": plate}
        vehicle = _touch_vehicle(db, plate, ev.vehicle_type, ev.timestamp, new_visit=True)
        _suspicious_checks(db, cfg, plate, vehicle, camera, ev)

    reason = None if plate_ok else ("Low confidence read: " + low_conf_text if low_conf_text else "Plate not readable")
    det = _record_detection(db, camera, ev, direction, plate, DetectionStatus.ENTRY_CREATED, reason,
                            needs_review=not plate_ok, vehicle=vehicle)
    try:
        session, tx = _open_session(
            db, plate=plate, vehicle=vehicle, vehicle_type=ev.vehicle_type, ts=ev.timestamp, camera=camera,
            detection=det, confidence=float(ev.plate_confidence or 0), source=source,
            is_simulated=ev.is_simulated, needs_review=not plate_ok,
        )
    except CountingError as e:  # concurrent insert from another process
        det.status, det.status_reason = DetectionStatus.DUPLICATE, str(e)
        return {"status": DetectionStatus.DUPLICATE, "detection_id": det.id, "plate": plate}

    if not plate_ok:
        create_alert(
            db, AlertType.OCR_FAILED, Severity.WARNING,
            "Number plate recognition failed (entry)",
            f"Vehicle counted at {camera.name if camera else 'entry'}; plate needs manual review. {reason}",
            camera_id=camera.id if camera else None, session_id=session.id, detection_id=det.id,
            plate_number=low_conf_text, is_simulated=ev.is_simulated,
        )
    check_capacity_alerts(db, session.category, ev.is_simulated)
    emit_occupancy(db)
    return {"status": DetectionStatus.ENTRY_CREATED, "detection_id": det.id, "session_id": session.id,
            "transaction_id": tx.id, "plate": plate, "category": session.category}


def _process_exit(db, cfg, camera, ev, direction, plate, plate_ok, low_conf_text, source):
    vehicle = _touch_vehicle(db, plate, ev.vehicle_type, ev.timestamp, new_visit=False) if plate_ok else None
    session, method = _find_exit_match(db, cfg, plate, plate_ok, ev.vehicle_type)
    needs_review = method in (ExitStatus.FUZZY_MATCHED, ExitStatus.UNREAD_MATCHED) or session is None or not plate_ok
    reason = {
        ExitStatus.MATCHED: None,
        ExitStatus.FUZZY_MATCHED: f"Fuzzy matched to {session.plate_number}" if session else None,
        ExitStatus.UNREAD_MATCHED: "Matched to oldest unread session",
        None: "No active session found",
    }[method]
    status = DetectionStatus.EXIT_RECORDED if (session or plate_ok) else DetectionStatus.FAILED_OCR
    det = _record_detection(db, camera, ev, direction, plate, status, reason, needs_review=needs_review, vehicle=vehicle)

    if session is not None:
        if method == ExitStatus.UNREAD_MATCHED and plate_ok and session.plate_number is None:
            session.plate_number = plate  # we learned the plate on the way out
            session.vehicle_id = vehicle.id if vehicle else None
        tx = _close_session(db, session, ev.timestamp, camera=camera, detection=det, status=method, source=source,
                            plate=plate, confidence=float(ev.plate_confidence or 0))
        if not plate_ok:
            create_alert(
                db, AlertType.OCR_FAILED, Severity.INFO, "Number plate recognition failed (exit)",
                f"Exit at {camera.name if camera else 'exit'} matched to unread session #{session.id}.",
                camera_id=camera.id if camera else None, session_id=session.id, detection_id=det.id,
                is_simulated=ev.is_simulated,
            )
        check_capacity_alerts(db, session.category, ev.is_simulated)
        emit_occupancy(db)
        return {"status": DetectionStatus.EXIT_RECORDED, "match": method, "detection_id": det.id,
                "session_id": session.id, "transaction_id": tx.id, "plate": plate or session.plate_number}

    # Unmatched: record, alert, but DO NOT decrement occupancy.
    tx = ExitTransaction(
        session_id=None, camera_id=camera.id if camera else None, detection_id=det.id, plate_number=plate,
        vehicle_type=ev.vehicle_type, confidence=float(ev.plate_confidence or 0), timestamp=ev.timestamp,
        source=source, status=ExitStatus.UNMATCHED,
        notes="" if plate_ok else ("Low confidence read: " + low_conf_text if low_conf_text else "Plate not readable"),
    )
    db.add(tx)
    db.flush()
    events.emit(db, "exit", exit_out(tx))
    create_alert(
        db, AlertType.UNMATCHED_EXIT, Severity.WARNING,
        f"Unmatched vehicle exit: {plate or low_conf_text or 'unreadable plate'}",
        "No active parking session found. Link it to a session from Vehicle Exit to correct the count.",
        camera_id=camera.id if camera else None, detection_id=det.id, plate_number=plate or low_conf_text,
        is_simulated=ev.is_simulated, data={"exit_transaction_id": tx.id},
    )
    return {"status": "UNMATCHED", "detection_id": det.id, "transaction_id": tx.id, "plate": plate}


# -------------------------------------------------- public: manual operations
def manual_entry(db: Session, user: User, plate_text: str, vehicle_type: str, ts: datetime | None,
                 camera_id: int | None = None, notes: str = "", ip: str | None = None) -> dict:
    with _lock:
        cfg = settings_store.get_all(db)
        plate = normalize_plate(plate_text)
        if not is_valid_plate(plate, int(cfg["min_plate_length"]), int(cfg["max_plate_length"]), cfg["plate_regex"]):
            raise CountingError("Invalid registration number")
        if vehicle_type not in VehicleType.ALL:
            raise CountingError("Invalid vehicle type")
        ts = ensure_aware(ts) or utcnow()
        if _active_session(db, plate):
            raise CountingError(f"{plate} already has an active parking session", 409)
        camera = db.get(Camera, camera_id) if camera_id else None
        vehicle = _touch_vehicle(db, plate, vehicle_type, ts, new_visit=True)
        ev = DetectionEvent(plate_text=plate, plate_confidence=1.0, vehicle_type=vehicle_type, timestamp=ts)
        _suspicious_checks(db, cfg, plate, vehicle, camera, ev)
        session, tx = _open_session(
            db, plate=plate, vehicle=vehicle, vehicle_type=vehicle_type, ts=ts, camera=camera, detection=None,
            confidence=1.0, source=TxSource.MANUAL, is_simulated=False, user=user, notes=notes,
        )
        audit(db, user, "MANUAL_ENTRY", "parking_session", session.id, {"plate": plate, "vehicle_type": vehicle_type, "notes": notes}, ip)
        check_capacity_alerts(db, session.category)
        emit_occupancy(db)
        db.commit()
        return {"session": session_out(session), "transaction": entry_out(tx)}


def manual_exit(db: Session, user: User, *, plate_text: str | None = None, session_id: int | None = None,
                ts: datetime | None = None, notes: str = "", ip: str | None = None) -> dict:
    with _lock:
        if session_id:
            session = db.get(ParkingSession, session_id)
        else:
            plate = normalize_plate(plate_text)
            session = _active_session(db, plate) if plate else None
        if session is None or session.status != SessionStatus.ACTIVE:
            raise CountingError("No active parking session found", 404)
        ts = ensure_aware(ts) or utcnow()
        if ts < ensure_aware(session.entry_time):
            raise CountingError("Exit time cannot be before entry time")
        tx = _close_session(db, session, ts, status=ExitStatus.MANUAL_MATCHED, source=TxSource.MANUAL,
                            confidence=1.0, user=user, notes=notes)
        audit(db, user, "MANUAL_EXIT", "parking_session", session.id, {"plate": session.plate_number, "notes": notes}, ip)
        check_capacity_alerts(db, session.category)
        emit_occupancy(db)
        db.commit()
        return {"session": session_out(session), "transaction": exit_out(tx)}


def cancel_entry(db: Session, user: User, entry_id: int, reason: str, ip: str | None = None) -> dict:
    """Cancel a false entry (e.g. a mis-detection). Removes the vehicle from the count."""
    with _lock:
        tx = db.get(EntryTransaction, entry_id)
        if tx is None:
            raise CountingError("Entry transaction not found", 404)
        if tx.status == EntryStatus.CANCELLED:
            raise CountingError("Entry already cancelled", 409)
        session = db.get(ParkingSession, tx.session_id)
        tx.status = EntryStatus.CANCELLED
        tx.notes = f"{tx.notes}\nCancelled: {reason}".strip()
        if session:
            session.status = SessionStatus.CANCELLED
            for ex in db.query(ExitTransaction).filter(ExitTransaction.session_id == session.id).all():
                if ex.status != ExitStatus.CANCELLED:
                    ex.status = ExitStatus.CANCELLED
                    ex.notes = f"{ex.notes}\nCancelled with entry #{tx.id}".strip()
        audit(db, user, "CANCEL_ENTRY", "entry_transaction", tx.id, {"reason": reason, "plate": tx.plate_number}, ip)
        events.emit(db, "entry_updated", entry_out(tx))
        emit_occupancy(db)
        db.commit()
        return entry_out(tx)


def cancel_exit(db: Session, user: User, exit_id: int, reason: str, ip: str | None = None) -> dict:
    """Cancel a wrong exit; re-opens the session so the vehicle counts as inside again."""
    with _lock:
        tx = db.get(ExitTransaction, exit_id)
        if tx is None:
            raise CountingError("Exit transaction not found", 404)
        if tx.status == ExitStatus.CANCELLED:
            raise CountingError("Exit already cancelled", 409)
        if tx.session_id and tx.status in ExitStatus.COUNTED:
            session = db.get(ParkingSession, tx.session_id)
            if session and session.status == SessionStatus.CLOSED:
                if session.plate_number and db.query(ParkingSession).filter(
                    ParkingSession.plate_number == session.plate_number,
                    ParkingSession.status == SessionStatus.ACTIVE,
                ).first():
                    raise CountingError("Cannot re-open: vehicle has a newer active session", 409)
                session.status = SessionStatus.ACTIVE
                session.exit_time = session.duration_seconds = session.exit_camera_id = session.exit_confidence = None
                session.exit_vehicle_image = session.exit_plate_image = None
        tx.status = ExitStatus.CANCELLED
        tx.notes = f"{tx.notes}\nCancelled: {reason}".strip()
        audit(db, user, "CANCEL_EXIT", "exit_transaction", tx.id, {"reason": reason, "plate": tx.plate_number}, ip)
        events.emit(db, "exit_updated", exit_out(tx))
        emit_occupancy(db)
        db.commit()
        return exit_out(tx)


def resolve_unmatched_exit(db: Session, user: User, exit_id: int, session_id: int, ip: str | None = None) -> dict:
    """Link an UNMATCHED exit to an active session, closing it."""
    with _lock:
        tx = db.get(ExitTransaction, exit_id)
        if tx is None or tx.status != ExitStatus.UNMATCHED:
            raise CountingError("Exit transaction is not unmatched", 409)
        session = db.get(ParkingSession, session_id)
        if session is None or session.status != SessionStatus.ACTIVE:
            raise CountingError("Session is not active", 409)
        ts = ensure_aware(tx.timestamp)
        session.status = SessionStatus.CLOSED
        session.exit_time = max(ts, ensure_aware(session.entry_time))
        session.duration_seconds = int((session.exit_time - ensure_aware(session.entry_time)).total_seconds())
        session.exit_camera_id = tx.camera_id
        session.exit_confidence = tx.confidence
        det = db.get(VehicleDetection, tx.detection_id) if tx.detection_id else None
        if det:
            session.exit_vehicle_image, session.exit_plate_image = det.vehicle_image_path, det.plate_image_path
            det.needs_review, det.reviewed_by_id, det.reviewed_at = False, user.id, utcnow()
        tx.session_id = session.id
        tx.status = ExitStatus.MANUAL_MATCHED
        tx.created_by_id = user.id
        tx.notes = f"{tx.notes}\nLinked to session #{session.id} by {user.username}".strip()
        from ..models import Alert  # local import avoids cycle at module load
        for a in db.query(Alert).filter(Alert.alert_type == AlertType.UNMATCHED_EXIT, Alert.is_resolved.is_(False)).all():
            if (a.data or {}).get("exit_transaction_id") == tx.id:
                a.is_resolved, a.resolved_by_id, a.resolved_at = True, user.id, utcnow()
        audit(db, user, "RESOLVE_UNMATCHED_EXIT", "exit_transaction", tx.id, {"session_id": session.id}, ip)
        events.emit(db, "exit", {**exit_out(tx), "session": session_out(session)})
        check_capacity_alerts(db, session.category)
        emit_occupancy(db)
        db.commit()
        return {"transaction": exit_out(tx), "session": session_out(session)}


def correct_session_plate(db: Session, user: User, session_id: int, plate_text: str, ip: str | None = None) -> dict:
    with _lock:
        cfg = settings_store.get_all(db)
        plate = normalize_plate(plate_text)
        if not is_valid_plate(plate, int(cfg["min_plate_length"]), int(cfg["max_plate_length"]), cfg["plate_regex"]):
            raise CountingError("Invalid registration number")
        session = db.get(ParkingSession, session_id)
        if session is None:
            raise CountingError("Session not found", 404)
        if session.status == SessionStatus.ACTIVE:
            other = _active_session(db, plate)
            if other and other.id != session.id:
                raise CountingError(f"{plate} already has active session #{other.id}", 409)
        old = session.plate_number
        vehicle = _touch_vehicle(db, plate, session.vehicle_type, ensure_aware(session.entry_time), new_visit=old is None)
        session.plate_number = plate
        session.vehicle_id = vehicle.id
        session.needs_review = False
        session.category = category_for(session.vehicle_type, vehicle) if session.status == SessionStatus.ACTIVE else session.category
        for t in db.query(EntryTransaction).filter(EntryTransaction.session_id == session.id).all():
            t.plate_number = plate
        for t in db.query(ExitTransaction).filter(ExitTransaction.session_id == session.id).all():
            t.plate_number = plate
        audit(db, user, "CORRECT_PLATE", "parking_session", session.id, {"old": old, "new": plate}, ip)
        events.emit(db, "session_updated", session_out(session))
        db.commit()
        return session_out(session)


def review_detection(db: Session, user: User, detection_id: int, corrected_plate: str | None,
                     vehicle_type: str | None, ip: str | None = None) -> dict:
    """Operator review of a detection: confirm or correct plate / type, and
    propagate the correction to the linked session."""
    with _lock:
        det = db.get(VehicleDetection, detection_id)
        if det is None:
            raise CountingError("Detection not found", 404)
        plate = normalize_plate(corrected_plate) if corrected_plate else None
        changes = {}
        if vehicle_type and vehicle_type in VehicleType.ALL and vehicle_type != det.vehicle_type:
            changes["vehicle_type"] = [det.vehicle_type, vehicle_type]
            det.vehicle_type = vehicle_type
        if plate and plate != det.plate_number:
            changes["plate"] = [det.plate_number, plate]
            det.corrected_plate = plate
        det.needs_review = False
        det.reviewed_by_id = user.id
        det.reviewed_at = utcnow()
        db.flush()
        result = {"detection": detection_out(det)}
        entry = db.query(EntryTransaction).filter(EntryTransaction.detection_id == det.id).first()
        exit_tx = db.query(ExitTransaction).filter(ExitTransaction.detection_id == det.id).first()
        audit(db, user, "REVIEW_DETECTION", "vehicle_detection", det.id, changes, ip)
        db.commit()
        if plate and entry:
            result["session"] = correct_session_plate(db, user, entry.session_id, plate, ip)
        elif plate and exit_tx:
            if exit_tx.status == ExitStatus.UNMATCHED:
                s = _active_session(db, plate)
                if s:
                    result.update(resolve_unmatched_exit(db, user, exit_tx.id, s.id, ip))
            elif exit_tx.session_id:
                result["session"] = correct_session_plate(db, user, exit_tx.session_id, plate, ip)
        if vehicle_type and entry:
            s = db.get(ParkingSession, entry.session_id)
            if s and s.vehicle_type != vehicle_type:
                s.vehicle_type = vehicle_type
                entry.vehicle_type = vehicle_type
                if s.status == SessionStatus.ACTIVE and s.category != ParkingCategory.RESERVED:
                    s.category = entry.category = VEHICLE_TYPE_TO_CATEGORY[vehicle_type]
                emit_occupancy(db)
                db.commit()
        return result
