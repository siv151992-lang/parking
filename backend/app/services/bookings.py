"""Office parking reservations.

All reservation changes go through this module. Rules (editable in Settings):
  * a booking is a time window on one slot of one office, for the employee's own vehicle
    or for a visitor (booked by an employee);
  * how far ahead, shortest / longest booking, bookings per employee per day;
  * a slot can only hold one CONFIRMED / CHECKED_IN booking at a time. This is checked under
    a process lock with the slot row locked, and PostgreSQL also enforces it with an
    exclusion constraint (migration 0004), so it holds even across processes;
  * a booking that is not checked in within `booking_no_show_minutes` of its start is
    released (NO_SHOW) by the maintenance job.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    AlertType,
    BookingStatus,
    Office,
    OfficeFloor,
    OfficeZone,
    ParkingSlot,
    Role,
    Severity,
    SlotBooking,
    SlotStatus,
    User,
    Vehicle,
    VehicleType,
)
from . import events, settings_store
from .alerts import create_alert
from .audit import audit
from .plates import normalize_plate
from .timeutil import ensure_aware, facility_tz, utcnow

_lock = threading.RLock()
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I
QR_PREFIX = "OPB1"


class BookingError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Visitor:
    name: str
    plate: str
    vehicle_type: str = VehicleType.CAR
    phone: str = ""


# ------------------------------------------------------------------ helpers
def new_code(db: Session) -> str:
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.query(SlotBooking.id).filter(SlotBooking.code == code).first():
            return code


def qr_payload(b: SlotBooking) -> str:
    """Text inside the QR code: prefix, booking code and a secret token (a typed code alone is not enough to forge one)."""
    return f"{QR_PREFIX}:{b.code}:{b.qr_token}"


def _overlapping(db: Session, slot_ids, start: datetime, end: datetime, exclude_id: int | None = None):
    q = db.query(SlotBooking).filter(
        SlotBooking.slot_id.in_(slot_ids),
        SlotBooking.status.in_(BookingStatus.HOLDING),
        SlotBooking.start_at < end,
        SlotBooking.end_at > start,
    )
    if exclude_id:
        q = q.filter(SlotBooking.id != exclude_id)
    return q


def _hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def validate_window(db: Session, office: Office, start: datetime, end: datetime, *, is_new: bool = True,
                    staff: bool = False) -> None:
    """Raise BookingError if the window breaks a rule. Staff (bookings.manage) may book further ahead."""
    cfg = settings_store.get_all(db)
    start, end = ensure_aware(start), ensure_aware(end)
    now = utcnow()
    if end <= start:
        raise BookingError("The end time must be after the start time")
    minutes = (end - start).total_seconds() / 60
    if minutes < int(cfg["booking_min_minutes"]):
        raise BookingError(f"Book at least {cfg['booking_min_minutes']} minutes")
    if minutes > int(cfg["booking_max_hours"]) * 60:
        raise BookingError(f"A booking can last at most {cfg['booking_max_hours']} hours")
    if is_new and start < now - timedelta(minutes=5):
        raise BookingError("The start time is in the past")
    if not staff and start > now + timedelta(days=int(cfg["booking_max_days_ahead"])):
        raise BookingError(f"You can book at most {cfg['booking_max_days_ahead']} days ahead")
    if not office.is_active:
        raise BookingError("This office is not taking bookings", 409)
    if not office.is_24h:
        tz = facility_tz(db)
        ls, le = start.astimezone(tz), end.astimezone(tz)
        opens, closes = _hhmm(office.open_time), _hhmm(office.close_time)
        same_day = ls.date() == le.date() or (le.time() == time(0, 0) and le.date() == ls.date() + timedelta(days=1))
        end_t = time(23, 59, 59) if le.time() == time(0, 0) and le.date() != ls.date() else le.time()
        if not same_day or ls.time() < opens or end_t > closes:
            raise BookingError(f"{office.name} parking is open {office.open_time}-{office.close_time}: book within those hours")


def slot_states(db: Session, office: Office, start: datetime, end: datetime, user: User | None = None) -> list[dict]:
    """Every slot of the office with its state for [start, end):
    AVAILABLE, BOOKED (reserved by someone), OCCUPIED (checked in now), MINE, ASSIGNED, OUT_OF_SERVICE."""
    slots = db.query(ParkingSlot).filter(ParkingSlot.office_id == office.id).order_by(ParkingSlot.code).all()
    busy = {}
    if slots:
        for b in _overlapping(db, [s.id for s in slots], start, end):
            busy[b.slot_id] = b
    out = []
    for s in slots:
        b = busy.get(s.id)
        if s.status == SlotStatus.OUT_OF_SERVICE:
            state = "OUT_OF_SERVICE"
        elif b is not None and user is not None and b.user_id == user.id:
            state = "MINE"
        elif b is not None:
            state = "OCCUPIED" if b.status == BookingStatus.CHECKED_IN else "BOOKED"
        elif s.assigned_user_id and (user is None or s.assigned_user_id != user.id):
            state = "ASSIGNED"
        else:
            state = "AVAILABLE"
        out.append({"slot": s, "state": state, "booking": b})
    return out


def _check_slot(slot: ParkingSlot, office: Office, user: User, vehicle_type: str, is_visitor: bool):
    if slot.office_id != office.id:
        raise BookingError("That slot belongs to another office")
    if slot.status != SlotStatus.ACTIVE:
        raise BookingError(f"Slot {slot.code} is out of service", 409)
    if slot.vehicle_type != vehicle_type:
        raise BookingError(f"Slot {slot.code} is for {slot.vehicle_type.replace('_', ' ').lower()} parking")
    if slot.is_visitor and not is_visitor:
        raise BookingError(f"Slot {slot.code} is reserved for visitors")
    if slot.assigned_user_id and slot.assigned_user_id != user.id:
        raise BookingError(f"Slot {slot.code} is assigned to another person", 409)


def _choose_slot(db: Session, office: Office, user: User, vehicle_type: str, start, end, *, is_visitor: bool,
                 prefer_ev: bool, prefer_accessible: bool) -> ParkingSlot:
    """Automatic allocation: the person's own assigned slot first, then the closest match to their preferences."""
    candidates = (
        db.query(ParkingSlot)
        .filter(ParkingSlot.office_id == office.id, ParkingSlot.status == SlotStatus.ACTIVE,
                ParkingSlot.vehicle_type == vehicle_type,
                (ParkingSlot.assigned_user_id.is_(None)) | (ParkingSlot.assigned_user_id == user.id))
        .join(OfficeZone, OfficeZone.id == ParkingSlot.zone_id)
        .join(OfficeFloor, OfficeFloor.id == OfficeZone.floor_id)
        .order_by(OfficeFloor.level, OfficeZone.name, ParkingSlot.code)
        .all()
    )
    if not is_visitor:
        candidates = [s for s in candidates if not s.is_visitor]
    if not candidates:
        raise BookingError("This office has no slots for this vehicle type", 409)
    busy = {b.slot_id for b in _overlapping(db, [s.id for s in candidates], start, end)}
    free = [s for s in candidates if s.id not in busy]
    if not free:
        raise BookingError("No free slot for this time. Try another time or office.", 409)

    def score(s: ParkingSlot):
        return (
            0 if s.assigned_user_id == user.id else 1,
            0 if (is_visitor and s.is_visitor) else 1,
            0 if s.is_ev == prefer_ev else 1,                     # do not take an EV charger without needing one
            0 if s.is_accessible == prefer_accessible else 1,      # keep accessible slots for those who need them
        )
    return min(free, key=score)


def _emit(db: Session, b: SlotBooking):
    from ..serializers import booking_out
    events.emit(db, "booking", booking_out(b))


# ---------------------------------------------------------------- create
def create_booking(db: Session, actor: User, *, office_id: int, start: datetime, end: datetime,
                   vehicle_id: int | None = None, slot_id: int | None = None, visitor: Visitor | None = None,
                   prefer_ev: bool = False, prefer_accessible: bool = False, notes: str = "",
                   for_user: User | None = None, staff: bool = False, ip: str | None = None) -> SlotBooking:
    """Reserve a slot. `for_user`: book on someone's behalf (bookings.manage only, checked by the API)."""
    owner = for_user or actor
    start, end = ensure_aware(start), ensure_aware(end)
    with _lock:
        try:
            office = db.get(Office, office_id)
            if office is None:
                raise BookingError("Office not found", 404)
            validate_window(db, office, start, end, staff=staff)
            cfg = settings_store.get_all(db)

            # --- vehicle
            vehicle = None
            if visitor is not None:
                if not cfg["visitor_bookings_enabled"]:
                    raise BookingError("Visitor bookings are switched off", 403)
                plate = normalize_plate(visitor.plate)
                if not visitor.name.strip():
                    raise BookingError("Enter the visitor's name")
                if not plate:
                    raise BookingError("Enter the visitor's vehicle number")
                vehicle_type = visitor.vehicle_type
            else:
                vehicle = db.get(Vehicle, vehicle_id) if vehicle_id else None
                if vehicle is None or vehicle.owner_user_id != owner.id:
                    raise BookingError("Choose one of your registered vehicles")
                plate, vehicle_type = vehicle.plate_number, vehicle.vehicle_type
                # --- per-day limit (own bookings, not visitors)
                tz = facility_tz(db)
                local = start.astimezone(tz)
                day_s = datetime.combine(local.date(), time.min, tzinfo=tz)
                same_day = db.query(func.count(SlotBooking.id)).filter(
                    SlotBooking.user_id == owner.id, SlotBooking.visitor_name.is_(None),
                    SlotBooking.status.in_(BookingStatus.HOLDING),
                    SlotBooking.start_at >= day_s, SlotBooking.start_at < day_s + timedelta(days=1)).scalar()
                if same_day >= int(cfg["booking_max_per_day"]):
                    raise BookingError(f"You already have {same_day} booking(s) on {local:%d %b}: the limit is "
                                       f"{cfg['booking_max_per_day']} per day", 409)

            # --- the same vehicle cannot be booked twice at the same time (any office)
            if db.query(SlotBooking.id).filter(
                SlotBooking.plate_number == plate, SlotBooking.status.in_(BookingStatus.HOLDING),
                SlotBooking.start_at < end, SlotBooking.end_at > start,
            ).first():
                raise BookingError(f"{plate} already has a booking at that time", 409)

            # --- slot
            is_visitor = visitor is not None
            if slot_id:
                slot = db.query(ParkingSlot).filter(ParkingSlot.id == slot_id).with_for_update().first()
                if slot is None:
                    raise BookingError("Slot not found", 404)
                _check_slot(slot, office, owner, vehicle_type, is_visitor)
                if _overlapping(db, [slot.id], start, end).first():
                    raise BookingError(f"Slot {slot.code} is already booked for that time", 409)
            else:
                slot = _choose_slot(db, office, owner, vehicle_type, start, end, is_visitor=is_visitor,
                                    prefer_ev=prefer_ev, prefer_accessible=prefer_accessible)
                db.query(ParkingSlot).filter(ParkingSlot.id == slot.id).with_for_update().first()

            b = SlotBooking(
                code=new_code(db), qr_token=secrets.token_urlsafe(18), user_id=owner.id, office_id=office.id,
                slot_id=slot.id, slot_code=slot.code, vehicle_id=vehicle.id if vehicle else None, plate_number=plate,
                vehicle_type=vehicle_type, visitor_name=visitor.name.strip() if visitor else None,
                visitor_phone=(visitor.phone.strip() or None) if visitor else None,
                start_at=start, end_at=end, status=BookingStatus.CONFIRMED, notes=notes[:500],
            )
            nested = db.begin_nested()
            try:
                db.add(b)
                db.flush()
                nested.commit()
            except IntegrityError:
                nested.rollback()  # PostgreSQL exclusion constraint: another process booked it first
                raise BookingError(f"Slot {slot.code} was just booked by someone else. Try again.", 409) from None
            audit(db, actor, "CREATE_BOOKING", "booking", b.id,
                  {"code": b.code, "office": office.name, "slot": slot.code, "plate": plate,
                   "start": start.isoformat(), "end": end.isoformat(), "visitor": b.visitor_name,
                   "for_user": owner.username if for_user else None}, ip)
            _emit(db, b)
            db.commit()
            return b
        except Exception:
            db.rollback()
            raise


# --------------------------------------------------------------- changes
def _can_change(b: SlotBooking, actor: User, manage: bool):
    if not manage and b.user_id != actor.id:
        raise BookingError("Booking not found", 404)


def cancel_booking(db: Session, b: SlotBooking, actor: User, reason: str = "", *, manage: bool = False,
                   ip: str | None = None) -> SlotBooking:
    with _lock:
        _can_change(b, actor, manage)
        if b.status != BookingStatus.CONFIRMED:
            raise BookingError(f"A {b.status.lower().replace('_', ' ')} booking cannot be cancelled", 409)
        b.status = BookingStatus.CANCELLED
        b.cancelled_at = utcnow()
        b.cancel_reason = (reason or "")[:255]
        audit(db, actor, "CANCEL_BOOKING", "booking", b.id, {"code": b.code, "reason": b.cancel_reason}, ip)
        _emit(db, b)
        db.commit()
        return b


def change_booking(db: Session, b: SlotBooking, actor: User, start: datetime, end: datetime, *, manage: bool = False,
                   ip: str | None = None) -> SlotBooking:
    """Move or resize a booking on the same slot (start can only change before check-in)."""
    start, end = ensure_aware(start), ensure_aware(end)
    with _lock:
        try:
            _can_change(b, actor, manage)
            if b.status == BookingStatus.CHECKED_IN:
                if abs((start - ensure_aware(b.start_at)).total_seconds()) > 60:
                    raise BookingError("The vehicle is already parked: only the end time can change", 409)
            elif b.status != BookingStatus.CONFIRMED:
                raise BookingError(f"A {b.status.lower().replace('_', ' ')} booking cannot be changed", 409)
            if end <= utcnow():
                raise BookingError("The end time is in the past")
            office = db.get(Office, b.office_id)
            validate_window(db, office, start, end, is_new=b.status == BookingStatus.CONFIRMED, staff=manage)
            if b.slot_id is None:
                raise BookingError("The slot of this booking was removed", 409)
            db.query(ParkingSlot).filter(ParkingSlot.id == b.slot_id).with_for_update().first()
            if _overlapping(db, [b.slot_id], start, end, exclude_id=b.id).first():
                raise BookingError(f"Slot {b.slot_code} is already booked for part of that time", 409)
            old = {"start": ensure_aware(b.start_at).isoformat(), "end": ensure_aware(b.end_at).isoformat()}
            b.start_at, b.end_at = start, end
            try:
                db.flush()
            except IntegrityError:
                raise BookingError(f"Slot {b.slot_code} was just booked by someone else", 409) from None
            audit(db, actor, "CHANGE_BOOKING", "booking", b.id,
                  {"code": b.code, "from": old, "to": {"start": start.isoformat(), "end": end.isoformat()}}, ip)
            _emit(db, b)
            db.commit()
            return b
        except Exception:
            db.rollback()
            raise


# ------------------------------------------------------------- security
def find_for_scan(db: Session, text: str) -> SlotBooking:
    """Booking from a scanned QR code (OPB1:CODE:TOKEN) or a typed booking code / vehicle number."""
    text = (text or "").strip()
    if text.upper().startswith(QR_PREFIX + ":"):
        parts = text.split(":")
        if len(parts) != 3:
            raise BookingError("Not a parking QR code", 400)
        b = db.query(SlotBooking).filter(SlotBooking.code == parts[1].upper()).first()
        if b is None or not secrets.compare_digest(b.qr_token, parts[2]):
            raise BookingError("Invalid QR code: not issued by this system", 404)
        return b
    code = normalize_plate(text)
    b = db.query(SlotBooking).filter(SlotBooking.code == code).first()
    if b:
        return b
    # by vehicle number: the booking that is current or next for this plate today
    now = utcnow()
    b = (db.query(SlotBooking).filter(SlotBooking.plate_number == code, SlotBooking.status.in_(BookingStatus.HOLDING),
                                      SlotBooking.end_at > now)
         .order_by(SlotBooking.start_at).first())
    if b is None:
        raise BookingError("No current booking for this code or vehicle number", 404)
    return b


def verdict(db: Session, b: SlotBooking) -> dict:
    """What security should do with this booking right now."""
    cfg = settings_store.get_all(db)
    now = utcnow()
    start, end = ensure_aware(b.start_at), ensure_aware(b.end_at)
    early = timedelta(minutes=int(cfg["booking_checkin_early_minutes"]))
    if b.status == BookingStatus.CHECKED_IN:
        return {"action": "CHECK_OUT", "ok": True, "message": "Parked. Check out when the vehicle leaves."}
    if b.status != BookingStatus.CONFIRMED:
        return {"action": "NONE", "ok": False, "message": f"Booking is {b.status.lower().replace('_', ' ')}"}
    if now < start - early:
        return {"action": "NONE", "ok": False, "message": f"Too early: check-in opens {int(early.total_seconds() // 60)} min before the start"}
    if now >= end:
        return {"action": "NONE", "ok": False, "message": "The booking has ended"}
    return {"action": "CHECK_IN", "ok": True, "message": "Valid booking: check in"}


def check_in(db: Session, b: SlotBooking, guard: User, ip: str | None = None) -> SlotBooking:
    with _lock:
        v = verdict(db, b)
        if v["action"] != "CHECK_IN":
            raise BookingError(v["message"], 409)
        b.status, b.checked_in_at, b.handled_by_id = BookingStatus.CHECKED_IN, utcnow(), guard.id
        audit(db, guard, "BOOKING_CHECK_IN", "booking", b.id, {"code": b.code, "plate": b.plate_number}, ip)
        _emit(db, b)
        db.commit()
        return b


def check_out(db: Session, b: SlotBooking, guard: User, ip: str | None = None) -> SlotBooking:
    with _lock:
        if b.status != BookingStatus.CHECKED_IN:
            raise BookingError("This vehicle is not checked in", 409)
        b.status, b.checked_out_at, b.handled_by_id = BookingStatus.COMPLETED, utcnow(), guard.id
        audit(db, guard, "BOOKING_CHECK_OUT", "booking", b.id, {"code": b.code, "plate": b.plate_number}, ip)
        _emit(db, b)
        db.commit()
        return b


# ---------------------------------------------------------- maintenance
def sweep(db: Session) -> dict:
    """Release no-shows and raise one overstay alert per booking. Run every minute."""
    cfg = settings_store.get_all(db)
    now = utcnow()
    released = 0
    with _lock:
        late = now - timedelta(minutes=int(cfg["booking_no_show_minutes"]))
        for b in db.query(SlotBooking).filter(SlotBooking.status == BookingStatus.CONFIRMED,
                                              SlotBooking.start_at < late).limit(500):
            b.status = BookingStatus.NO_SHOW
            audit(db, None, "BOOKING_NO_SHOW", "booking", b.id, {"code": b.code, "slot": b.slot_code})
            _emit(db, b)
            released += 1
        overstays = 0
        for b in db.query(SlotBooking).filter(SlotBooking.status == BookingStatus.CHECKED_IN,
                                              SlotBooking.end_at < now - timedelta(minutes=15)).limit(500):
            alert = create_alert(
                db, AlertType.SUSPICIOUS_VEHICLE, Severity.WARNING,
                f"Overstay: {b.plate_number} in slot {b.slot_code}",
                f"Booking {b.code} ended {ensure_aware(b.end_at):%H:%M} UTC but the vehicle is still checked in.",
                plate_number=b.plate_number, data={"reason": "booking_overstay", "booking_id": b.id},
                dedupe_seconds=24 * 3600,
            )
            overstays += 1 if alert is not None else 0
        db.commit()
    return {"released": released, "overstay_checked": overstays}


def is_staff(user: User) -> bool:
    return user.role in Role.STAFF
