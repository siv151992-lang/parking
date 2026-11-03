"""Parking rows: free spaces row by row.

Each row has a capacity and its own cameras at the row entrance: an ENTRY row
camera sees vehicles driving into the row, an EXIT row camera sees them leaving.
Row occupancy == ACTIVE row_presence records, so it can never go negative.
The main gate cameras (cameras without a row) keep counting the whole car park.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import AlertType, Camera, ParkingRow, PresenceClose, PresenceStatus, RowPresence, Severity
from . import settings_store
from .alerts import create_alert

WARNING_PCT = 90


def row_counts(db: Session) -> dict[int, int]:
    rows = (
        db.query(RowPresence.row_id, func.count(RowPresence.id))
        .filter(RowPresence.status == PresenceStatus.ACTIVE)
        .group_by(RowPresence.row_id)
        .all()
    )
    return {rid: n for rid, n in rows}


def row_out(r: ParkingRow, occupied: int, cameras: list[Camera] | None = None) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "capacity": r.capacity,
        "occupied": occupied,
        "available": max(0, r.capacity - occupied),
        "occupancy_pct": round(occupied * 100 / r.capacity, 1) if r.capacity else 0.0,
        "sort_order": r.sort_order,
        "is_active": r.is_active,
        "alert_state": r.alert_state,
        "cameras": [{"id": c.id, "name": c.name, "direction": c.direction, "status": c.status} for c in (cameras or [])],
    }


def rows_snapshot(db: Session, include_inactive: bool = False) -> list[dict]:
    counts = row_counts(db)
    q = db.query(ParkingRow)
    if not include_inactive:
        q = q.filter(ParkingRow.is_active.is_(True))
    rows = q.order_by(ParkingRow.sort_order, ParkingRow.name).all()
    cams: dict[int, list[Camera]] = {}
    for c in db.query(Camera).filter(Camera.row_id.isnot(None)).order_by(Camera.direction).all():
        cams.setdefault(c.row_id, []).append(c)
    return [row_out(r, counts.get(r.id, 0), cams.get(r.id)) for r in rows]


def check_row_alerts(db: Session, row: ParkingRow, is_simulated: bool = False):
    """Alert once when a row reaches 90% and once when it is full (5% hysteresis)."""
    if not row.capacity or not settings_store.get(db, "capacity_alerts_enabled"):
        return
    occ = row_counts(db).get(row.id, 0)
    pct = occ * 100 / row.capacity
    if pct >= 100:
        new_state = "FULL"
    elif pct >= WARNING_PCT:
        new_state = "WARNING"
    elif pct < WARNING_PCT - 5:
        new_state = "NORMAL"
    else:
        new_state = row.alert_state
    rank = {"NORMAL": 0, "WARNING": 1, "FULL": 2}
    if new_state != row.alert_state and rank[new_state] > rank[row.alert_state]:
        data = {"row_id": row.id, "row": row.name, "occupied": occ, "capacity": row.capacity}
        if new_state == "FULL":
            create_alert(db, AlertType.CAPACITY_FULL, Severity.CRITICAL, f"{row.name} is FULL",
                         f"All {row.capacity} spaces in {row.name} are taken.", data=data, is_simulated=is_simulated)
        else:
            create_alert(db, AlertType.CAPACITY_WARNING, Severity.WARNING, f"{row.name} almost full",
                         f"{row.capacity - occ} of {row.capacity} spaces free in {row.name}.", data=data,
                         is_simulated=is_simulated)
    row.alert_state = new_state
    db.flush()


def close_presence(p: RowPresence, ts: datetime, reason: str, camera_id: int | None = None):
    p.status = PresenceStatus.CLOSED
    p.exited_at = ts
    p.close_reason = reason
    p.exit_camera_id = camera_id


def close_presence_for_session(db: Session, session, ts: datetime):
    """A vehicle left the car park through a gate: it is no longer in any row."""
    q = db.query(RowPresence).filter(RowPresence.status == PresenceStatus.ACTIVE)
    if session.plate_number:
        q = q.filter((RowPresence.session_id == session.id) | (RowPresence.plate_number == session.plate_number))
    else:
        q = q.filter(RowPresence.session_id == session.id)
    closed = q.all()
    for p in closed:
        close_presence(p, ts, PresenceClose.GATE_EXIT)
    if closed:
        db.flush()
    return len(closed)


def set_row_count(db: Session, row: ParkingRow, count: int, ts: datetime) -> dict:
    """Operator correction of a row's count. Lowering it closes the oldest
    vehicles in the row; raising it adds vehicles without a known plate."""
    count = max(0, int(count))
    active = (
        db.query(RowPresence)
        .filter(RowPresence.row_id == row.id, RowPresence.status == PresenceStatus.ACTIVE)
        .order_by(RowPresence.entered_at.desc())
        .all()
    )
    before = len(active)
    for p in active[count:]:
        close_presence(p, ts, PresenceClose.RESET)
    for _ in range(count - before):
        db.add(RowPresence(row_id=row.id, plate_number=None, status=PresenceStatus.ACTIVE, entered_at=ts))
    row.alert_state = "NORMAL"
    db.flush()
    return {"before": before, "after": count}
