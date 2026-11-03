"""Parking rows: capacity and free spaces row by row."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require
from ..models import Camera, ParkingRow, PresenceStatus, RowPresence
from ..schemas import RowCountIn, RowIn, RowUpdate
from ..services import rows as row_service
from ..services.audit import audit
from ..services.counting import _lock
from ..services.occupancy import emit_occupancy
from ..services.timeutil import utcnow

router = APIRouter(prefix="/api/rows", tags=["Parking Rows"])


def _get(db: Session, rid: int) -> ParkingRow:
    r = db.get(ParkingRow, rid)
    if r is None:
        raise HTTPException(404, "Row not found")
    return r


def _one(db: Session, r: ParkingRow) -> dict:
    return next(x for x in row_service.rows_snapshot(db, include_inactive=True) if x["id"] == r.id)


@router.get("")
def list_rows(db: Session = Depends(get_db), _=Depends(require("occupancy.view"))):
    return row_service.rows_snapshot(db, include_inactive=True)


@router.post("", status_code=201)
def create_row(body: RowIn, request: Request, db: Session = Depends(get_db), user=Depends(require("occupancy.manage"))):
    if db.query(ParkingRow).filter(ParkingRow.name == body.name.strip()).first():
        raise HTTPException(409, "A row with this name already exists")
    r = ParkingRow(**{**body.model_dump(), "name": body.name.strip()})
    db.add(r)
    db.flush()
    audit(db, user, "CREATE_ROW", "parking_row", r.id, body.model_dump(), client_ip(request))
    emit_occupancy(db)
    db.commit()
    return _one(db, r)


@router.put("/{rid}")
def update_row(rid: int, body: RowUpdate, request: Request, db: Session = Depends(get_db), user=Depends(require("occupancy.manage"))):
    r = _get(db, rid)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if db.query(ParkingRow).filter(ParkingRow.name == changes["name"], ParkingRow.id != rid).first():
            raise HTTPException(409, "A row with this name already exists")
    for k, v in changes.items():
        setattr(r, k, v)
    db.flush()
    row_service.check_row_alerts(db, r)
    audit(db, user, "UPDATE_ROW", "parking_row", rid, changes, client_ip(request))
    emit_occupancy(db)
    db.commit()
    return _one(db, r)


@router.delete("/{rid}", status_code=204)
def delete_row(rid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("occupancy.manage"))):
    r = _get(db, rid)
    n_cams = db.query(Camera).filter(Camera.row_id == rid).count()
    audit(db, user, "DELETE_ROW", "parking_row", rid, {"name": r.name, "cameras_unlinked": n_cams}, client_ip(request))
    db.query(Camera).filter(Camera.row_id == rid).update({Camera.row_id: None}, synchronize_session=False)
    db.query(RowPresence).filter(RowPresence.row_id == rid).delete(synchronize_session=False)
    db.delete(r)
    db.flush()
    emit_occupancy(db)
    db.commit()


@router.post("/{rid}/count")
def set_count(rid: int, body: RowCountIn, request: Request, db: Session = Depends(get_db),
              user=Depends(require("transactions.manual"))):
    """Correct a row's count by hand (e.g. after a camera outage)."""
    with _lock:
        r = _get(db, rid)
        result = row_service.set_row_count(db, r, body.count, utcnow())
        audit(db, user, "SET_ROW_COUNT", "parking_row", rid, {**result, "reason": body.reason}, client_ip(request))
        row_service.check_row_alerts(db, r)
        emit_occupancy(db)
        db.commit()
    return _one(db, r)


@router.get("/{rid}/vehicles")
def row_vehicles(rid: int, db: Session = Depends(get_db), _=Depends(require("vehicles.view"))):
    _get(db, rid)
    items = (
        db.query(RowPresence)
        .filter(RowPresence.row_id == rid, RowPresence.status == PresenceStatus.ACTIVE)
        .order_by(RowPresence.entered_at.desc())
        .all()
    )
    return [{"id": p.id, "plate_number": p.plate_number, "vehicle_type": p.vehicle_type, "entered_at": p.entered_at,
             "session_id": p.session_id, "is_simulated": p.is_simulated} for p in items]
