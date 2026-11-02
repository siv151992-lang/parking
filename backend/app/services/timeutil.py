"""Timezone helpers: 'today' and report periods are in the facility timezone."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from . import settings_store


def facility_tz(db: Session) -> ZoneInfo:
    try:
        return ZoneInfo(settings_store.get(db, "timezone"))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def day_bounds(db: Session, day: date | None = None) -> tuple[datetime, datetime]:
    """UTC start/end of a local calendar day."""
    tz = facility_tz(db)
    day = day or datetime.now(tz).date()
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def range_bounds(db: Session, start: date, end: date) -> tuple[datetime, datetime]:
    """UTC bounds covering local dates [start, end] inclusive."""
    s, _ = day_bounds(db, start)
    _, e = day_bounds(db, end)
    return s, e


def local_today(db: Session) -> date:
    return datetime.now(facility_tz(db)).date()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
