"""Occupancy is derived from ACTIVE parking sessions (the single source of
truth), so it can never drift or go negative."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    AlertType,
    EntryStatus,
    EntryTransaction,
    ExitStatus,
    ExitTransaction,
    ParkingCapacity,
    ParkingCategory,
    ParkingSession,
    SessionStatus,
    Severity,
)
from . import events, settings_store
from .alerts import create_alert
from .rows import rows_snapshot


def ensure_capacity_rows(db: Session):
    existing = {c.category for c in db.query(ParkingCapacity).all()}
    defaults = {ParkingCategory.CAR: 300, ParkingCategory.TWO_WHEELER: 150, ParkingCategory.HEAVY: 30, ParkingCategory.RESERVED: 20}
    for cat in ParkingCategory.ALL:
        if cat not in existing:
            db.add(ParkingCapacity(category=cat, label=ParkingCategory.LABELS[cat], total_capacity=defaults[cat]))
    db.flush()


def active_counts(db: Session) -> dict[str, int]:
    rows = (
        db.query(ParkingSession.category, func.count(ParkingSession.id))
        .filter(ParkingSession.status == SessionStatus.ACTIVE)
        .group_by(ParkingSession.category)
        .all()
    )
    return {cat: n for cat, n in rows}


def snapshot(db: Session) -> dict:
    counts = active_counts(db)
    categories = []
    total_cap = total_occ = 0
    for cap in db.query(ParkingCapacity).order_by(ParkingCapacity.id).all():
        occ = counts.get(cap.category, 0)
        if cap.is_active:
            total_cap += cap.total_capacity
        total_occ += occ
        categories.append(
            {
                "category": cap.category,
                "label": cap.label,
                "total_capacity": cap.total_capacity,
                "occupied": occ,
                "available": max(0, cap.total_capacity - occ),
                "occupancy_pct": round(occ * 100 / cap.total_capacity, 1) if cap.total_capacity else 0.0,
                "alert_threshold_pct": cap.alert_threshold_pct,
                "is_active": cap.is_active,
                "alert_state": cap.alert_state,
            }
        )
    return {
        "total_capacity": total_cap,
        "occupied": total_occ,
        "available": max(0, total_cap - total_occ),
        "occupancy_pct": round(total_occ * 100 / total_cap, 1) if total_cap else 0.0,
        "categories": categories,
        "rows": rows_snapshot(db),
    }


def check_capacity_alerts(db: Session, category: str | None = None, is_simulated: bool = False):
    """Raise WARNING/FULL alerts once per state transition (hysteresis of 5%)."""
    if not settings_store.get(db, "capacity_alerts_enabled"):
        return
    counts = active_counts(db)
    q = db.query(ParkingCapacity)
    if category:
        q = q.filter(ParkingCapacity.category == category)
    for cap in q.all():
        if not cap.total_capacity:
            continue
        occ = counts.get(cap.category, 0)
        pct = occ * 100 / cap.total_capacity
        if pct >= 100:
            new_state = "FULL"
        elif pct >= cap.alert_threshold_pct:
            new_state = "WARNING"
        elif pct < cap.alert_threshold_pct - 5:
            new_state = "NORMAL"
        else:
            new_state = cap.alert_state  # inside hysteresis band
        if new_state == cap.alert_state:
            continue
        rank = {"NORMAL": 0, "WARNING": 1, "FULL": 2}
        if rank[new_state] > rank[cap.alert_state]:
            if new_state == "FULL":
                create_alert(
                    db, AlertType.CAPACITY_FULL, Severity.CRITICAL,
                    f"{cap.label} is FULL",
                    f"{occ}/{cap.total_capacity} spaces occupied.",
                    data={"category": cap.category, "occupied": occ, "capacity": cap.total_capacity},
                    is_simulated=is_simulated,
                )
            else:
                create_alert(
                    db, AlertType.CAPACITY_WARNING, Severity.WARNING,
                    f"{cap.label} at {pct:.0f}% capacity",
                    f"{occ}/{cap.total_capacity} spaces occupied (threshold {cap.alert_threshold_pct}%).",
                    data={"category": cap.category, "occupied": occ, "capacity": cap.total_capacity},
                    is_simulated=is_simulated,
                )
        cap.alert_state = new_state
    db.flush()


def reconcile(db: Session) -> dict:
    """Vehicles inside = valid entries - counted exits. Verify against the
    number of ACTIVE sessions; any difference indicates data corruption."""
    entries = db.query(func.count(EntryTransaction.id)).filter(EntryTransaction.status == EntryStatus.VALID).scalar() or 0
    exits = (
        db.query(func.count(ExitTransaction.id))
        .filter(ExitTransaction.status.in_(ExitStatus.COUNTED), ExitTransaction.session_id.isnot(None))
        .scalar()
        or 0
    )
    active = db.query(func.count(ParkingSession.id)).filter(ParkingSession.status == SessionStatus.ACTIVE).scalar() or 0
    unmatched = db.query(func.count(ExitTransaction.id)).filter(ExitTransaction.status == ExitStatus.UNMATCHED).scalar() or 0
    expected = entries - exits
    return {
        "total_valid_entries": entries,
        "total_counted_exits": exits,
        "expected_inside": expected,
        "active_sessions": active,
        "discrepancy": expected - active,
        "is_consistent": expected == active,
        "pending_unmatched_exits": unmatched,
    }


def emit_occupancy(db: Session):
    events.emit(db, "occupancy", snapshot(db))
