from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..anpr.engine import ANPREngine
from ..anpr.manager import camera_manager
from ..database import get_db
from ..deps import require
from ..models import (
    Alert,
    Camera,
    CameraStatus,
    DetectionStatus,
    EntryStatus,
    EntryTransaction,
    ExitStatus,
    ExitTransaction,
    VehicleDetection,
    VehicleType,
)
from ..serializers import detection_out
from ..services import events
from ..services.occupancy import reconcile, snapshot
from ..services.timeutil import day_bounds, facility_tz

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def compute_stats(db: Session) -> dict:
    s, e = day_bounds(db)
    entries_q = db.query(EntryTransaction).filter(EntryTransaction.timestamp >= s, EntryTransaction.timestamp < e,
                                                  EntryTransaction.status == EntryStatus.VALID)
    entries_today = entries_q.count()
    type_counts = dict(entries_q.with_entities(EntryTransaction.vehicle_type, func.count(EntryTransaction.id))
                       .group_by(EntryTransaction.vehicle_type).all())
    sim_entries = entries_q.filter(EntryTransaction.source == "SIMULATED").count()
    exits_today = db.query(func.count(ExitTransaction.id)).filter(
        ExitTransaction.timestamp >= s, ExitTransaction.timestamp < e, ExitTransaction.status.in_(ExitStatus.COUNTED)).scalar()
    unmatched_today = db.query(func.count(ExitTransaction.id)).filter(
        ExitTransaction.timestamp >= s, ExitTransaction.timestamp < e, ExitTransaction.status == ExitStatus.UNMATCHED).scalar()
    det_today = db.query(VehicleDetection.status, func.count(VehicleDetection.id)).filter(
        VehicleDetection.detected_at >= s, VehicleDetection.detected_at < e).group_by(VehicleDetection.status).all()
    det_counts = dict(det_today)
    cams = db.query(Camera).all()
    occ = snapshot(db)
    return {
        "entries_today": entries_today,
        "exits_today": exits_today,
        "simulated_entries_today": sim_entries,
        "unmatched_exits_today": unmatched_today,
        "vehicles_inside": occ["occupied"],
        "total_capacity": occ["total_capacity"],
        "available_spaces": occ["available"],
        "occupancy_pct": occ["occupancy_pct"],
        "cars_today": type_counts.get(VehicleType.CAR, 0),
        "two_wheelers_today": type_counts.get(VehicleType.TWO_WHEELER, 0),
        "commercial_today": type_counts.get(VehicleType.COMMERCIAL, 0),
        "detections_today": sum(det_counts.values()),
        "duplicates_blocked_today": det_counts.get(DetectionStatus.DUPLICATE, 0) + det_counts.get(DetectionStatus.COOLDOWN, 0),
        "cameras_total": len(cams),
        "cameras_online": sum(1 for c in cams if c.status == CameraStatus.ONLINE),
        "cameras_offline": sum(1 for c in cams if c.status in (CameraStatus.OFFLINE, CameraStatus.CONNECTING)),
        "cameras_disabled": sum(1 for c in cams if c.status == CameraStatus.DISABLED),
        "simulated_cameras": sum(1 for c in cams if c.is_simulated),
        "unresolved_alerts": db.query(func.count(Alert.id)).filter(Alert.is_resolved.is_(False)).scalar(),
        "unread_alerts": db.query(func.count(Alert.id)).filter(Alert.is_read.is_(False)).scalar(),
        "occupancy": occ,
    }


@router.get("/stats")
def stats(db: Session = Depends(get_db), _=Depends(require("dashboard.view"))):
    return compute_stats(db)


@router.get("/hourly")
def hourly_today(db: Session = Depends(get_db), _=Depends(require("dashboard.view"))):
    tz = facility_tz(db)
    s, e = day_bounds(db)
    en = Counter(t.astimezone(tz).hour for (t,) in db.query(EntryTransaction.timestamp).filter(
        EntryTransaction.timestamp >= s, EntryTransaction.timestamp < e, EntryTransaction.status == EntryStatus.VALID))
    ex = Counter(t.astimezone(tz).hour for (t,) in db.query(ExitTransaction.timestamp).filter(
        ExitTransaction.timestamp >= s, ExitTransaction.timestamp < e, ExitTransaction.status.in_(ExitStatus.COUNTED)))
    return [{"hour": f"{h:02d}:00", "entries": en[h], "exits": ex[h]} for h in range(24)]


@router.get("/recent-detections")
def recent_detections(limit: int = 20, db: Session = Depends(get_db), _=Depends(require("dashboard.view"))):
    rows = (db.query(VehicleDetection).filter(VehicleDetection.status != DetectionStatus.COOLDOWN)
            .order_by(VehicleDetection.detected_at.desc()).limit(min(limit, 100)).all())
    return [detection_out(d) for d in rows]


@router.get("/system")
def system_status(db: Session = Depends(get_db), _=Depends(require("dashboard.view"))):
    return {
        "anpr_engine": ANPREngine.status(),
        "workers": {cid: w.runtime() for cid, w in camera_manager.workers.items()},
        "websocket_clients": events.manager.client_count,
        "reconciliation": reconcile(db),
    }
