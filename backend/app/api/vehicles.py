from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require
from ..models import EntryTransaction, ExitTransaction, ParkingSession, Vehicle, VehicleDetection
from ..schemas import VehicleCreate, VehicleUpdate
from ..serializers import detection_out, entry_out, exit_out, session_out, vehicle_out
from ..services import settings_store
from ..services.audit import audit
from ..services.plates import is_valid_plate, normalize_plate

router = APIRouter(prefix="/api/vehicles", tags=["Vehicles"])


@router.get("")
def list_vehicles(q: str = "", vehicle_type: str = "", flag: str = "", page: int = Query(1, ge=1),
                  page_size: int = Query(25, ge=1, le=500), db: Session = Depends(get_db), _=Depends(require("vehicles.view"))):
    query = db.query(Vehicle)
    if q:
        query = query.filter(Vehicle.plate_number.ilike(f"%{normalize_plate(q) or q}%"))
    if vehicle_type:
        query = query.filter(Vehicle.vehicle_type == vehicle_type)
    if flag == "reserved":
        query = query.filter(Vehicle.is_reserved.is_(True))
    elif flag == "blacklisted":
        query = query.filter(Vehicle.is_blacklisted.is_(True))
    total = query.count()
    items = query.order_by(Vehicle.last_seen_at.desc().nullslast()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [vehicle_out(v) for v in items]}


@router.post("", status_code=201)
def create_vehicle(body: VehicleCreate, request: Request, db: Session = Depends(get_db), user=Depends(require("vehicles.manage"))):
    plate = normalize_plate(body.plate_number)
    cfg = settings_store.get_all(db)
    if not is_valid_plate(plate, int(cfg["min_plate_length"]), int(cfg["max_plate_length"]), cfg["plate_regex"]):
        raise HTTPException(400, "Invalid registration number")
    if db.query(Vehicle).filter(Vehicle.plate_number == plate).first():
        raise HTTPException(409, "Vehicle already registered")
    v = Vehicle(plate_number=plate, vehicle_type=body.vehicle_type, is_reserved=body.is_reserved,
                is_blacklisted=body.is_blacklisted, owner_name=body.owner_name, notes=body.notes)
    db.add(v)
    db.flush()
    audit(db, user, "CREATE_VEHICLE", "vehicle", v.id, body.model_dump(), client_ip(request))
    db.commit()
    return vehicle_out(v)


@router.put("/{vid}")
def update_vehicle(vid: int, body: VehicleUpdate, request: Request, db: Session = Depends(get_db), user=Depends(require("vehicles.manage"))):
    v = db.get(Vehicle, vid)
    if not v:
        raise HTTPException(404, "Vehicle not found")
    changes = body.model_dump(exclude_unset=True)
    for k, val in changes.items():
        setattr(v, k, val)
    audit(db, user, "UPDATE_VEHICLE", "vehicle", v.id, {"plate": v.plate_number, **changes}, client_ip(request))
    db.commit()
    return vehicle_out(v)


@router.get("/history/{plate}")
def vehicle_history(plate: str, db: Session = Depends(get_db), _=Depends(require("vehicles.view"))):
    """Complete movement history of one registration number."""
    p = normalize_plate(plate)
    v = db.query(Vehicle).filter(Vehicle.plate_number == p).first()
    sessions = db.query(ParkingSession).filter(ParkingSession.plate_number == p).order_by(ParkingSession.entry_time.desc()).limit(500).all()
    entries = db.query(EntryTransaction).filter(EntryTransaction.plate_number == p).order_by(EntryTransaction.timestamp.desc()).limit(500).all()
    exits = db.query(ExitTransaction).filter(ExitTransaction.plate_number == p).order_by(ExitTransaction.timestamp.desc()).limit(500).all()
    detections = (db.query(VehicleDetection).filter(VehicleDetection.plate_number == p)
                  .order_by(VehicleDetection.detected_at.desc()).limit(200).all())
    timeline = sorted(
        [{"type": "ENTRY", "time": t.timestamp, "camera": entry_out(t)["camera_name"], "status": t.status, "source": t.source,
          "session_id": t.session_id} for t in entries]
        + [{"type": "EXIT", "time": t.timestamp, "camera": exit_out(t)["camera_name"], "status": t.status, "source": t.source,
            "session_id": t.session_id} for t in exits],
        key=lambda x: x["time"], reverse=True,
    )
    durations = [s.duration_seconds for s in sessions if s.duration_seconds]
    return {
        "plate_number": p,
        "vehicle": vehicle_out(v) if v else None,
        "sessions": [session_out(s) for s in sessions],
        "timeline": timeline,
        "detections": [detection_out(d) for d in detections],
        "stats": {"visits": len(sessions), "avg_duration_seconds": int(sum(durations) / len(durations)) if durations else None,
                  "currently_inside": any(s.status == "ACTIVE" for s in sessions)},
    }
