"""Entry / exit transactions, parking sessions and manual corrections."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require
from ..models import EntryTransaction, ExitStatus, ExitTransaction, ParkingSession, SessionStatus
from ..schemas import CancelIn, CorrectPlateIn, ManualEntryIn, ManualExitIn, ResolveExitIn
from ..serializers import entry_out, exit_out, session_out
from ..services import counting
from ..services.plates import normalize_plate, plate_distance
from ..services.timeutil import range_bounds

router = APIRouter(prefix="/api", tags=["Transactions & Sessions"])


def _page(q, page: int, page_size: int):
    total = q.count()
    return total, q.offset((page - 1) * page_size).limit(page_size).all()


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except counting.CountingError as e:
        raise HTTPException(e.status_code, str(e))


# ------------------------------------------------------------------ entries
@router.get("/entries")
def list_entries(
    plate: str = "", start: date | None = None, end: date | None = None, camera_id: int | None = None,
    vehicle_type: str = "", source: str = "", status: str = "", page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500), db: Session = Depends(get_db), _=Depends(require("vehicles.view")),
):
    q = db.query(EntryTransaction)
    if plate:
        q = q.filter(EntryTransaction.plate_number.ilike(f"%{normalize_plate(plate) or plate}%"))
    if start or end:
        s, e = range_bounds(db, start or end, end or start)
        q = q.filter(EntryTransaction.timestamp >= s, EntryTransaction.timestamp < e)
    if camera_id:
        q = q.filter(EntryTransaction.camera_id == camera_id)
    if vehicle_type:
        q = q.filter(EntryTransaction.vehicle_type == vehicle_type)
    if source:
        q = q.filter(EntryTransaction.source == source)
    if status:
        q = q.filter(EntryTransaction.status == status)
    total, items = _page(q.order_by(EntryTransaction.timestamp.desc()), page, page_size)
    return {"total": total, "items": [entry_out(t) for t in items]}


@router.post("/entries/manual", status_code=201)
def manual_entry(body: ManualEntryIn, request: Request, db: Session = Depends(get_db), user=Depends(require("transactions.manual"))):
    return _wrap(counting.manual_entry, db, user, body.plate_number, body.vehicle_type, body.timestamp, body.camera_id,
                 body.notes, client_ip(request))


@router.post("/entries/{entry_id}/cancel")
def cancel_entry(entry_id: int, body: CancelIn, request: Request, db: Session = Depends(get_db), user=Depends(require("transactions.correct"))):
    return _wrap(counting.cancel_entry, db, user, entry_id, body.reason, client_ip(request))


# -------------------------------------------------------------------- exits
@router.get("/exits")
def list_exits(
    plate: str = "", start: date | None = None, end: date | None = None, camera_id: int | None = None,
    vehicle_type: str = "", source: str = "", status: str = "", page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500), db: Session = Depends(get_db), _=Depends(require("vehicles.view")),
):
    q = db.query(ExitTransaction)
    if plate:
        q = q.filter(ExitTransaction.plate_number.ilike(f"%{normalize_plate(plate) or plate}%"))
    if start or end:
        s, e = range_bounds(db, start or end, end or start)
        q = q.filter(ExitTransaction.timestamp >= s, ExitTransaction.timestamp < e)
    if camera_id:
        q = q.filter(ExitTransaction.camera_id == camera_id)
    if vehicle_type:
        q = q.filter(ExitTransaction.vehicle_type == vehicle_type)
    if source:
        q = q.filter(ExitTransaction.source == source)
    if status:
        q = q.filter(ExitTransaction.status == status)
    total, items = _page(q.order_by(ExitTransaction.timestamp.desc()), page, page_size)
    return {"total": total, "items": [exit_out(t) for t in items]}


@router.post("/exits/manual", status_code=201)
def manual_exit(body: ManualExitIn, request: Request, db: Session = Depends(get_db), user=Depends(require("transactions.manual"))):
    if not body.plate_number and not body.session_id:
        raise HTTPException(400, "plate_number or session_id required")
    return _wrap(counting.manual_exit, db, user, plate_text=body.plate_number, session_id=body.session_id, ts=body.timestamp,
                 notes=body.notes, ip=client_ip(request))


@router.post("/exits/{exit_id}/cancel")
def cancel_exit(exit_id: int, body: CancelIn, request: Request, db: Session = Depends(get_db), user=Depends(require("transactions.correct"))):
    return _wrap(counting.cancel_exit, db, user, exit_id, body.reason, client_ip(request))


@router.post("/exits/{exit_id}/resolve")
def resolve_exit(exit_id: int, body: ResolveExitIn, request: Request, db: Session = Depends(get_db), user=Depends(require("transactions.manual"))):
    return _wrap(counting.resolve_unmatched_exit, db, user, exit_id, body.session_id, client_ip(request))


@router.get("/exits/{exit_id}/candidates")
def unmatched_candidates(exit_id: int, db: Session = Depends(get_db), _=Depends(require("transactions.manual"))):
    """Suggest active sessions that an unmatched exit most likely belongs to."""
    tx = db.get(ExitTransaction, exit_id)
    if not tx:
        raise HTTPException(404, "Exit not found")
    sessions = db.query(ParkingSession).filter(ParkingSession.status == SessionStatus.ACTIVE).all()
    scored = []
    for s in sessions:
        if tx.plate_number and s.plate_number:
            d = plate_distance(tx.plate_number, s.plate_number)
        else:
            d = 50 if s.plate_number else 5  # unread sessions are plausible for unread exits
        if s.vehicle_type != tx.vehicle_type:
            d += 2
        scored.append((d, s.entry_time, s))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [{**session_out(s), "distance": d} for d, _, s in scored[:15]]


# ----------------------------------------------------------------- sessions
@router.get("/sessions")
def list_sessions(
    plate: str = "", status: str = "", category: str = "", vehicle_type: str = "", start: date | None = None,
    end: date | None = None, needs_review: bool | None = None, include_simulated: bool = True,
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500),
    db: Session = Depends(get_db), _=Depends(require("vehicles.view")),
):
    q = db.query(ParkingSession)
    if plate:
        q = q.filter(ParkingSession.plate_number.ilike(f"%{normalize_plate(plate) or plate}%"))
    if status:
        q = q.filter(ParkingSession.status == status)
    if category:
        q = q.filter(ParkingSession.category == category)
    if vehicle_type:
        q = q.filter(ParkingSession.vehicle_type == vehicle_type)
    if start or end:
        s, e = range_bounds(db, start or end, end or start)
        q = q.filter(or_(ParkingSession.entry_time.between(s, e), ParkingSession.exit_time.between(s, e)))
    if needs_review is not None:
        q = q.filter(ParkingSession.needs_review.is_(needs_review))
    if not include_simulated:
        q = q.filter(ParkingSession.is_simulated.is_(False))
    total, items = _page(q.order_by(ParkingSession.entry_time.desc()), page, page_size)
    return {"total": total, "items": [session_out(s) for s in items]}


@router.get("/sessions/{sid}")
def get_session(sid: int, db: Session = Depends(get_db), _=Depends(require("vehicles.view"))):
    s = db.get(ParkingSession, sid)
    if not s:
        raise HTTPException(404, "Session not found")
    return {
        **session_out(s),
        "entries": [entry_out(t) for t in db.query(EntryTransaction).filter(EntryTransaction.session_id == sid)],
        "exits": [exit_out(t) for t in db.query(ExitTransaction).filter(ExitTransaction.session_id == sid)],
    }


@router.post("/sessions/{sid}/plate")
def correct_plate(sid: int, body: CorrectPlateIn, request: Request, db: Session = Depends(get_db), user=Depends(require("detections.review"))):
    return _wrap(counting.correct_session_plate, db, user, sid, body.plate_number, client_ip(request))


@router.get("/unmatched-exits")
def unmatched_exits(db: Session = Depends(get_db), _=Depends(require("vehicles.view"))):
    rows = db.query(ExitTransaction).filter(ExitTransaction.status == ExitStatus.UNMATCHED).order_by(ExitTransaction.timestamp.desc()).limit(200)
    return [exit_out(t) for t in rows]
