from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require
from ..models import VehicleDetection
from ..schemas import ReviewIn
from ..serializers import detection_out
from ..services import counting
from ..services.plates import normalize_plate
from ..services.timeutil import range_bounds

router = APIRouter(prefix="/api/detections", tags=["Detections & Review"])


@router.get("")
def list_detections(
    plate: str = "", camera_id: int | None = None, direction: str = "", status: str = "", needs_review: bool | None = None,
    is_simulated: bool | None = None, start: date | None = None, end: date | None = None, page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500), db: Session = Depends(get_db), _=Depends(require("vehicles.view")),
):
    q = db.query(VehicleDetection)
    if plate:
        q = q.filter(VehicleDetection.plate_number.ilike(f"%{normalize_plate(plate) or plate}%"))
    if camera_id:
        q = q.filter(VehicleDetection.camera_id == camera_id)
    if direction:
        q = q.filter(VehicleDetection.direction == direction)
    if status:
        q = q.filter(VehicleDetection.status == status)
    if needs_review is not None:
        q = q.filter(VehicleDetection.needs_review.is_(needs_review))
    if is_simulated is not None:
        q = q.filter(VehicleDetection.is_simulated.is_(is_simulated))
    if start or end:
        s, e = range_bounds(db, start or end, end or start)
        q = q.filter(VehicleDetection.detected_at >= s, VehicleDetection.detected_at < e)
    total = q.count()
    items = q.order_by(VehicleDetection.detected_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [detection_out(d) for d in items]}


@router.get("/{did}")
def get_detection(did: int, db: Session = Depends(get_db), _=Depends(require("vehicles.view"))):
    d = db.get(VehicleDetection, did)
    if not d:
        raise HTTPException(404, "Detection not found")
    return detection_out(d)


@router.post("/{did}/review")
def review(did: int, body: ReviewIn, request: Request, db: Session = Depends(get_db), user=Depends(require("detections.review"))):
    try:
        return counting.review_detection(db, user, did, body.corrected_plate, body.vehicle_type, client_ip(request))
    except counting.CountingError as e:
        raise HTTPException(e.status_code, str(e))
