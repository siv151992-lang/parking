"""Office parking: offices / floors / zones / slots (admin), availability, employees' vehicles
and reservations, and security check-in / check-out."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require
from ..models import (
    BookingStatus,
    Office,
    OfficeFloor,
    OfficeZone,
    ParkingSlot,
    Role,
    SlotBooking,
    SlotStatus,
    User,
    Vehicle,
)
from ..schemas import (
    BookingCancelIn,
    BookingChangeIn,
    BookingIn,
    FloorIn,
    MyVehicleIn,
    OfficeIn,
    OfficeUpdate,
    ProfileIn,
    ScanIn,
    SlotsBulkIn,
    SlotUpdate,
    ZoneIn,
)
from ..security import has_permission
from ..serializers import booking_out, office_out, slot_out, user_out, vehicle_out
from ..services import bookings as svc
from ..services.audit import audit
from ..services.plates import normalize_plate
from ..services.timeutil import day_bounds, ensure_aware, utcnow

router = APIRouter(prefix="/api", tags=["Office parking"])


def _run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except svc.BookingError as e:
        raise HTTPException(e.status_code, str(e)) from None


def _office(db: Session, oid: int) -> Office:
    o = db.get(Office, oid)
    if o is None:
        raise HTTPException(404, "Office not found")
    return o


def _fresh_office(db: Session, oid: int) -> dict:
    """The office as stored now (floors / zones collections reloaded after a change)."""
    db.expire_all()
    return office_out(db.get(Office, oid))


def _window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    start = ensure_aware(start) or utcnow()
    end = ensure_aware(end) or start + timedelta(hours=1)
    if end <= start:
        raise HTTPException(400, "The end time must be after the start time")
    if end - start > timedelta(days=7):
        raise HTTPException(400, "Choose a window of at most 7 days")
    return start, end


# ================================================================ offices
@router.get("/offices")
def list_offices(start: datetime | None = None, end: datetime | None = None, vehicle_type: str = "",
                 include_inactive: bool = False, db: Session = Depends(get_db), user=Depends(require("offices.view"))):
    """Offices with free-slot counts for a time window (default: the next hour)."""
    s, e = _window(start, end)
    q = db.query(Office)
    if not (include_inactive and has_permission(user.role, "offices.manage")):
        q = q.filter(Office.is_active.is_(True))
    out = []
    for o in q.order_by(Office.city, Office.name).all():
        states = svc.slot_states(db, o, s, e, user)
        if vehicle_type:
            states = [x for x in states if x["slot"].vehicle_type == vehicle_type]
        bookable = [x for x in states if not (x["slot"].is_visitor)]
        out.append({**office_out(o), "slots_total": len(states),
                    "slots_free": sum(1 for x in bookable if x["state"] == "AVAILABLE"),
                    "ev_free": sum(1 for x in bookable if x["state"] == "AVAILABLE" and x["slot"].is_ev),
                    "accessible_free": sum(1 for x in bookable if x["state"] == "AVAILABLE" and x["slot"].is_accessible),
                    "visitor_free": sum(1 for x in states if x["state"] == "AVAILABLE" and x["slot"].is_visitor)})
    return out


@router.get("/offices/{oid}/availability")
def availability(oid: int, start: datetime | None = None, end: datetime | None = None,
                 db: Session = Depends(get_db), user=Depends(require("offices.view"))):
    """Every slot with its state for the window: AVAILABLE, BOOKED, OCCUPIED, MINE, ASSIGNED, OUT_OF_SERVICE."""
    o = _office(db, oid)
    s, e = _window(start, end)
    staff = has_permission(user.role, "bookings.verify")
    slots = []
    for x in svc.slot_states(db, o, s, e, user):
        d = slot_out(x["slot"], x["state"])
        b = x["booking"]
        if b is not None and staff:  # security / managers see who is in the slot
            d["booking"] = {"id": b.id, "code": b.code, "plate_number": b.plate_number,
                            "user_name": (b.user.full_name or b.user.username) if b.user else None,
                            "visitor_name": b.visitor_name, "end_at": b.end_at}
        slots.append(d)
    return {"office": office_out(o), "start": s, "end": e, "slots": slots}


@router.post("/offices", status_code=201)
def create_office(body: OfficeIn, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    if db.query(Office).filter(func.lower(Office.name) == body.name.strip().lower()).first():
        raise HTTPException(409, "An office with this name already exists")
    o = Office(**{**body.model_dump(), "name": body.name.strip()})
    db.add(o)
    db.flush()
    audit(db, user, "CREATE_OFFICE", "office", o.id, body.model_dump(), client_ip(request))
    db.commit()
    return office_out(o)


@router.put("/offices/{oid}")
def update_office(oid: int, body: OfficeUpdate, request: Request, db: Session = Depends(get_db),
                  user=Depends(require("offices.manage"))):
    o = _office(db, oid)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and db.query(Office).filter(func.lower(Office.name) == changes["name"].strip().lower(),
                                                     Office.id != oid).first():
        raise HTTPException(409, "An office with this name already exists")
    for k, v in changes.items():
        setattr(o, k, v.strip() if isinstance(v, str) and k == "name" else v)
    audit(db, user, "UPDATE_OFFICE", "office", oid, changes, client_ip(request))
    db.commit()
    return office_out(o)


def _future_bookings(db: Session, **filters):
    q = db.query(func.count(SlotBooking.id)).filter(SlotBooking.status.in_(BookingStatus.HOLDING),
                                                     SlotBooking.end_at > utcnow())
    for k, v in filters.items():
        q = q.filter(getattr(SlotBooking, k).in_(v) if isinstance(v, list) else getattr(SlotBooking, k) == v)
    return q.scalar()


@router.delete("/offices/{oid}", status_code=204)
def delete_office(oid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    o = _office(db, oid)
    if _future_bookings(db, office_id=oid):
        raise HTTPException(409, "This office has current or upcoming bookings. Cancel them or mark the office inactive.")
    audit(db, user, "DELETE_OFFICE", "office", oid, {"name": o.name}, client_ip(request))
    db.query(SlotBooking).filter(SlotBooking.office_id == oid).delete(synchronize_session=False)
    db.query(ParkingSlot).filter(ParkingSlot.office_id == oid).delete(synchronize_session=False)
    db.delete(o)
    db.commit()


# ---- floors and zones
@router.post("/offices/{oid}/floors", status_code=201)
def add_floor(oid: int, body: FloorIn, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    o = _office(db, oid)
    if any(f.name.lower() == body.name.strip().lower() for f in o.floors):
        raise HTTPException(409, "This office already has a floor with that name")
    f = OfficeFloor(office_id=oid, name=body.name.strip(), level=body.level)
    db.add(f)
    db.flush()
    audit(db, user, "CREATE_FLOOR", "office", oid, {"floor": f.name, "level": f.level}, client_ip(request))
    db.commit()
    return _fresh_office(db, oid)


@router.put("/floors/{fid}")
def update_floor(fid: int, body: FloorIn, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    f = db.get(OfficeFloor, fid)
    if f is None:
        raise HTTPException(404, "Floor not found")
    if db.query(OfficeFloor).filter(OfficeFloor.office_id == f.office_id, func.lower(OfficeFloor.name) == body.name.strip().lower(),
                                    OfficeFloor.id != fid).first():
        raise HTTPException(409, "This office already has a floor with that name")
    f.name, f.level = body.name.strip(), body.level
    audit(db, user, "UPDATE_FLOOR", "office", f.office_id, {"floor_id": fid, **body.model_dump()}, client_ip(request))
    db.commit()
    return _fresh_office(db, f.office_id)


def _zone_slot_ids(db: Session, zone_ids: list[int]) -> list[int]:
    return [i for (i,) in db.query(ParkingSlot.id).filter(ParkingSlot.zone_id.in_(zone_ids))] if zone_ids else []


@router.delete("/floors/{fid}", status_code=204)
def delete_floor(fid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    f = db.get(OfficeFloor, fid)
    if f is None:
        raise HTTPException(404, "Floor not found")
    slot_ids = _zone_slot_ids(db, [z.id for z in f.zones])
    if slot_ids and _future_bookings(db, slot_id=slot_ids):
        raise HTTPException(409, "Slots on this floor have current or upcoming bookings")
    audit(db, user, "DELETE_FLOOR", "office", f.office_id, {"floor": f.name}, client_ip(request))
    if slot_ids:
        db.query(ParkingSlot).filter(ParkingSlot.id.in_(slot_ids)).delete(synchronize_session=False)
    db.delete(f)
    db.commit()


@router.post("/floors/{fid}/zones", status_code=201)
def add_zone(fid: int, body: ZoneIn, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    f = db.get(OfficeFloor, fid)
    if f is None:
        raise HTTPException(404, "Floor not found")
    if any(z.name.lower() == body.name.strip().lower() for z in f.zones):
        raise HTTPException(409, "This floor already has a zone with that name")
    db.add(OfficeZone(floor_id=fid, name=body.name.strip()))
    audit(db, user, "CREATE_ZONE", "office", f.office_id, {"floor": f.name, "zone": body.name}, client_ip(request))
    db.commit()
    return _fresh_office(db, f.office_id)


@router.put("/zones/{zid}")
def rename_zone(zid: int, body: ZoneIn, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    z = db.get(OfficeZone, zid)
    if z is None:
        raise HTTPException(404, "Zone not found")
    if db.query(OfficeZone).filter(OfficeZone.floor_id == z.floor_id, func.lower(OfficeZone.name) == body.name.strip().lower(),
                                   OfficeZone.id != zid).first():
        raise HTTPException(409, "This floor already has a zone with that name")
    z.name = body.name.strip()
    audit(db, user, "UPDATE_ZONE", "office", z.floor.office_id, {"zone_id": zid, "name": z.name}, client_ip(request))
    office_id = z.floor.office_id
    db.commit()
    return _fresh_office(db, office_id)


@router.delete("/zones/{zid}", status_code=204)
def delete_zone(zid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    z = db.get(OfficeZone, zid)
    if z is None:
        raise HTTPException(404, "Zone not found")
    slot_ids = _zone_slot_ids(db, [zid])
    if slot_ids and _future_bookings(db, slot_id=slot_ids):
        raise HTTPException(409, "Slots in this zone have current or upcoming bookings")
    audit(db, user, "DELETE_ZONE", "office", z.floor.office_id, {"zone": z.name}, client_ip(request))
    if slot_ids:
        db.query(ParkingSlot).filter(ParkingSlot.id.in_(slot_ids)).delete(synchronize_session=False)
    db.delete(z)
    db.commit()


# ---- slots
@router.get("/offices/{oid}/slots")
def list_slots(oid: int, db: Session = Depends(get_db), _=Depends(require("offices.manage"))):
    _office(db, oid)
    return [slot_out(s) for s in db.query(ParkingSlot).filter(ParkingSlot.office_id == oid).order_by(ParkingSlot.code)]


@router.post("/zones/{zid}/slots", status_code=201)
def add_slots(zid: int, body: SlotsBulkIn, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    """Create many slots at once: prefix + number (A-01 ... A-20)."""
    z = db.get(OfficeZone, zid)
    if z is None:
        raise HTTPException(404, "Zone not found")
    office_id = z.floor.office_id
    codes = [f"{body.prefix.strip()}{n:0{body.digits}d}" for n in range(body.start, body.start + body.count)]
    taken = {c for (c,) in db.query(ParkingSlot.code).filter(ParkingSlot.office_id == office_id, ParkingSlot.code.in_(codes))}
    if taken:
        raise HTTPException(409, f"These slot numbers already exist in this office: {', '.join(sorted(taken)[:10])}")
    for c in codes:
        db.add(ParkingSlot(office_id=office_id, zone_id=zid, code=c, vehicle_type=body.vehicle_type, is_ev=body.is_ev,
                           is_accessible=body.is_accessible, is_visitor=body.is_visitor))
    audit(db, user, "CREATE_SLOTS", "office", office_id, {"zone": z.name, "codes": f"{codes[0]}..{codes[-1]}",
                                                          "count": len(codes)}, client_ip(request))
    db.commit()
    return {"created": len(codes), "codes": codes}


@router.put("/slots/{sid}")
def update_slot(sid: int, body: SlotUpdate, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    s = db.get(ParkingSlot, sid)
    if s is None:
        raise HTTPException(404, "Slot not found")
    changes = body.model_dump(exclude_unset=True)
    if "code" in changes:
        changes["code"] = changes["code"].strip()
        if db.query(ParkingSlot).filter(ParkingSlot.office_id == s.office_id, ParkingSlot.code == changes["code"],
                                        ParkingSlot.id != sid).first():
            raise HTTPException(409, "Another slot in this office has that number")
    if changes.get("zone_id") is not None:
        z = db.get(OfficeZone, changes["zone_id"])
        if z is None or z.floor.office_id != s.office_id:
            raise HTTPException(400, "Zone not found in this office")
    if changes.get("assigned_user_id") is not None and db.get(User, changes["assigned_user_id"]) is None:
        raise HTTPException(400, "User not found")
    for k, v in changes.items():
        setattr(s, k, v)
    audit(db, user, "UPDATE_SLOT", "slot", sid, {"code": s.code, **changes}, client_ip(request))
    db.commit()
    return slot_out(s)


@router.delete("/slots/{sid}", status_code=204)
def delete_slot(sid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("offices.manage"))):
    s = db.get(ParkingSlot, sid)
    if s is None:
        raise HTTPException(404, "Slot not found")
    if _future_bookings(db, slot_id=sid):
        raise HTTPException(409, "This slot has current or upcoming bookings. Mark it out of service instead.")
    audit(db, user, "DELETE_SLOT", "slot", sid, {"code": s.code, "office_id": s.office_id}, client_ip(request))
    db.delete(s)
    db.commit()


# ================================================================ my vehicles / profile
@router.get("/me/vehicles")
def my_vehicles(db: Session = Depends(get_db), user=Depends(require("bookings.own"))):
    return [vehicle_out(v) for v in db.query(Vehicle).filter(Vehicle.owner_user_id == user.id).order_by(Vehicle.plate_number)]


@router.post("/me/vehicles", status_code=201)
def add_my_vehicle(body: MyVehicleIn, request: Request, db: Session = Depends(get_db), user=Depends(require("bookings.own"))):
    plate = normalize_plate(body.plate_number)
    if not plate or len(plate) < 3:
        raise HTTPException(400, "Enter a valid vehicle number")
    v = db.query(Vehicle).filter(Vehicle.plate_number == plate).first()
    if v is not None and v.owner_user_id not in (None, user.id):
        raise HTTPException(409, "This vehicle is registered to another person. Ask an administrator.")
    if v is None:
        v = Vehicle(plate_number=plate, vehicle_type=body.vehicle_type)
        db.add(v)
    elif v.owner_user_id == user.id:
        raise HTTPException(409, "You already registered this vehicle")
    v.owner_user_id, v.vehicle_type = user.id, body.vehicle_type
    v.owner_name = user.full_name or user.username
    if body.notes:
        v.notes = body.notes
    db.flush()
    audit(db, user, "ADD_MY_VEHICLE", "vehicle", v.id, {"plate": plate}, client_ip(request))
    db.commit()
    return vehicle_out(v)


@router.put("/me/vehicles/{vid}")
def update_my_vehicle(vid: int, body: MyVehicleIn, db: Session = Depends(get_db), user=Depends(require("bookings.own"))):
    v = db.get(Vehicle, vid)
    if v is None or v.owner_user_id != user.id:
        raise HTTPException(404, "Vehicle not found")
    if normalize_plate(body.plate_number) != v.plate_number:
        raise HTTPException(400, "The vehicle number cannot change: remove the vehicle and add the new one")
    v.vehicle_type, v.notes = body.vehicle_type, body.notes
    db.commit()
    return vehicle_out(v)


@router.delete("/me/vehicles/{vid}", status_code=204)
def remove_my_vehicle(vid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("bookings.own"))):
    v = db.get(Vehicle, vid)
    if v is None or v.owner_user_id != user.id:
        raise HTTPException(404, "Vehicle not found")
    if _future_bookings(db, vehicle_id=vid):
        raise HTTPException(409, "This vehicle has current or upcoming bookings. Cancel them first.")
    v.owner_user_id = None  # the plate stays in the ANPR registry / history
    audit(db, user, "REMOVE_MY_VEHICLE", "vehicle", vid, {"plate": v.plate_number}, client_ip(request))
    db.commit()


@router.put("/me/profile")
def update_profile(body: ProfileIn, request: Request, db: Session = Depends(get_db), user=Depends(require("bookings.own"))):
    changes = {k: v.strip() for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    for k, v in changes.items():
        setattr(user, k, v)
    audit(db, user, "UPDATE_PROFILE", "user", user.id, changes, client_ip(request))
    db.commit()
    return user_out(user)


# ================================================================ bookings
def _get_booking(db: Session, bid: int, user: User) -> SlotBooking:
    b = db.get(SlotBooking, bid)
    if b is None or (b.user_id != user.id and not has_permission(user.role, "bookings.verify")):
        raise HTTPException(404, "Booking not found")
    return b


@router.post("/bookings", status_code=201)
def create_booking(body: BookingIn, request: Request, db: Session = Depends(get_db), user=Depends(require("bookings.own"))):
    manage = has_permission(user.role, "bookings.manage")
    for_user = None
    if body.user_id and body.user_id != user.id:
        if not manage:
            raise HTTPException(403, "You can only book for yourself or a visitor")
        for_user = db.get(User, body.user_id)
        if for_user is None or not for_user.is_active:
            raise HTTPException(404, "User not found")
    visitor = svc.Visitor(body.visitor.name, body.visitor.plate_number, body.visitor.vehicle_type, body.visitor.phone) \
        if body.visitor else None
    b = _run(svc.create_booking, db, user, office_id=body.office_id, start=body.start_at, end=body.end_at,
             vehicle_id=body.vehicle_id, slot_id=body.slot_id, visitor=visitor, prefer_ev=body.prefer_ev,
             prefer_accessible=body.prefer_accessible, notes=body.notes, for_user=for_user, staff=manage,
             ip=client_ip(request))
    return booking_out(b, include_qr=True)


@router.get("/me/bookings")
def my_bookings(scope: str = Query("upcoming", pattern="^(upcoming|past|all)$"), page: int = Query(1, ge=1),
                page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user=Depends(require("bookings.own"))):
    q = db.query(SlotBooking).filter(SlotBooking.user_id == user.id)
    now = utcnow()
    if scope == "upcoming":
        q = q.filter(SlotBooking.status.in_(BookingStatus.HOLDING), SlotBooking.end_at > now).order_by(SlotBooking.start_at)
    elif scope == "past":
        q = q.filter(or_(SlotBooking.status.notin_(BookingStatus.HOLDING), SlotBooking.end_at <= now)) \
             .order_by(SlotBooking.start_at.desc())
    else:
        q = q.order_by(SlotBooking.start_at.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [booking_out(b, include_qr=True) for b in items]}


@router.get("/bookings")
def list_bookings(office_id: int | None = None, day: date | None = None, status: str = "", q: str = "",
                  page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                  db: Session = Depends(get_db), user=Depends(require("bookings.verify"))):
    """All bookings (security and managers). `day` = local date the booking overlaps (default: today)."""
    s, e = day_bounds(db, day)
    query = db.query(SlotBooking).filter(SlotBooking.start_at < e, SlotBooking.end_at > s)
    if office_id:
        query = query.filter(SlotBooking.office_id == office_id)
    if status:
        query = query.filter(SlotBooking.status == status)
    if q:
        like = f"%{q.strip()}%"
        query = query.outerjoin(User, User.id == SlotBooking.user_id).filter(or_(
            SlotBooking.code.ilike(like), SlotBooking.plate_number.ilike(f"%{normalize_plate(q) or q}%"),
            SlotBooking.visitor_name.ilike(like), SlotBooking.slot_code.ilike(like),
            User.full_name.ilike(like), User.username.ilike(like)))
    total = query.count()
    items = query.order_by(SlotBooking.start_at).offset((page - 1) * page_size).limit(page_size).all()
    counts = dict(db.query(SlotBooking.status, func.count(SlotBooking.id))
                  .filter(SlotBooking.start_at < e, SlotBooking.end_at > s,
                          *([SlotBooking.office_id == office_id] if office_id else []))
                  .group_by(SlotBooking.status).all())
    return {"total": total, "counts": counts, "items": [booking_out(b) for b in items]}


@router.get("/bookings/{bid}")
def get_booking(bid: int, db: Session = Depends(get_db), user=Depends(require("bookings.own"))):
    b = _get_booking(db, bid, user)
    return {**booking_out(b, include_qr=b.user_id == user.id or has_permission(user.role, "bookings.manage")),
            "verdict": svc.verdict(db, b)}


@router.post("/bookings/{bid}/cancel")
def cancel_booking(bid: int, body: BookingCancelIn, request: Request, db: Session = Depends(get_db),
                   user=Depends(require("bookings.own"))):
    b = _get_booking(db, bid, user)
    manage = has_permission(user.role, "bookings.manage")
    if b.user_id != user.id and not manage:
        raise HTTPException(403, "Only the person who booked or a manager can cancel")
    return booking_out(_run(svc.cancel_booking, db, b, user, body.reason, manage=manage, ip=client_ip(request)), include_qr=True)


@router.put("/bookings/{bid}")
def change_booking(bid: int, body: BookingChangeIn, request: Request, db: Session = Depends(get_db),
                   user=Depends(require("bookings.own"))):
    b = _get_booking(db, bid, user)
    manage = has_permission(user.role, "bookings.manage")
    if b.user_id != user.id and not manage:
        raise HTTPException(403, "Only the person who booked or a manager can change the booking")
    return booking_out(_run(svc.change_booking, db, b, user, body.start_at, body.end_at, manage=manage,
                            ip=client_ip(request)), include_qr=True)


# ---- security
@router.post("/bookings/scan")
def scan(body: ScanIn, db: Session = Depends(get_db), user=Depends(require("bookings.verify"))):
    """Look up a booking from a scanned QR code, a typed booking code, or a vehicle number."""
    b = _run(svc.find_for_scan, db, body.text)
    return {**booking_out(b), "verdict": svc.verdict(db, b)}


@router.post("/bookings/{bid}/check-in")
def check_in(bid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("bookings.verify"))):
    b = _get_booking(db, bid, user)
    return booking_out(_run(svc.check_in, db, b, user, client_ip(request)))


@router.post("/bookings/{bid}/check-out")
def check_out(bid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("bookings.verify"))):
    b = _get_booking(db, bid, user)
    return booking_out(_run(svc.check_out, db, b, user, client_ip(request)))


# ---- people (for assigning slots / booking on behalf)
@router.get("/people")
def people(q: str = "", db: Session = Depends(get_db), _=Depends(require("bookings.manage"))):
    query = db.query(User).filter(User.is_active.is_(True))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.username.ilike(like), User.full_name.ilike(like), User.email.ilike(like)))
    return [{"id": u.id, "name": u.full_name or u.username, "username": u.username, "role": u.role,
             "department": u.department} for u in query.order_by(User.full_name).limit(50)]


__all__ = ["router", "Role", "SlotStatus"]
