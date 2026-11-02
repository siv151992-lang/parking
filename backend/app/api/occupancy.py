from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require
from ..models import ParkingCapacity
from ..schemas import CapacityUpdate
from ..services.audit import audit
from ..services.occupancy import check_capacity_alerts, emit_occupancy, reconcile, snapshot

router = APIRouter(prefix="/api/occupancy", tags=["Parking Occupancy"])


@router.get("")
def get_occupancy(db: Session = Depends(get_db), _=Depends(require("occupancy.view"))):
    return snapshot(db)


@router.put("/{category}")
def update_capacity(category: str, body: CapacityUpdate, request: Request, db: Session = Depends(get_db),
                    user=Depends(require("occupancy.manage"))):
    cap = db.query(ParkingCapacity).filter(ParkingCapacity.category == category).first()
    if not cap:
        raise HTTPException(404, "Unknown parking category")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(cap, k, v)
    audit(db, user, "UPDATE_CAPACITY", "parking_capacity", category, changes, client_ip(request))
    db.flush()
    check_capacity_alerts(db, category)
    emit_occupancy(db)
    db.commit()
    return snapshot(db)


@router.get("/reconcile")
def reconcile_counts(db: Session = Depends(get_db), _=Depends(require("occupancy.view"))):
    """Verify: vehicles inside = valid entries - counted exits = ACTIVE sessions."""
    return reconcile(db)
