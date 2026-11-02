"""Runtime-editable system settings stored in the system_settings table."""
import threading
import time

from sqlalchemy.orm import Session

from ..models import SystemSetting

DEFAULTS: dict = {
    "facility_name": "Smart Parking Facility",
    "timezone": "Asia/Kolkata",
    # duplicate prevention
    "default_cooldown_seconds": 60,
    "reentry_auto_close_minutes": 15,
    # plate recognition
    "min_plate_length": 4,
    "max_plate_length": 12,
    "plate_regex": "",
    "fuzzy_match_enabled": True,
    "fuzzy_max_distance": 1,
    "unread_exit_matching": True,
    # alerts
    "duplicate_alerts_enabled": True,
    "suspicious_repeat_entries": 3,
    "suspicious_window_minutes": 30,
    "max_parking_hours": 24,
    "capacity_alerts_enabled": True,
    # retention
    "detection_retention_days": 90,
}

DESCRIPTIONS = {
    "facility_name": "Name shown on reports and the dashboard",
    "timezone": "IANA timezone used for 'today' counters and reports",
    "default_cooldown_seconds": "Default cooldown for new cameras: same plate is ignored on the same direction for this many seconds",
    "reentry_auto_close_minutes": "If a plate re-enters while its session is older than this, the missed exit is auto-closed instead of flagged as duplicate",
    "min_plate_length": "Minimum characters for a valid registration number",
    "max_plate_length": "Maximum characters for a valid registration number",
    "plate_regex": "Optional regex every normalised plate must match (empty = any alphanumeric)",
    "fuzzy_match_enabled": "Match exits to sessions tolerating OCR confusions (O/0, I/1, B/8 ...)",
    "fuzzy_max_distance": "Maximum edit distance for fuzzy exit matching",
    "unread_exit_matching": "Match an unreadable exit plate to the oldest unreadable active session of the same category",
    "duplicate_alerts_enabled": "Raise an alert for duplicate entry attempts",
    "suspicious_repeat_entries": "Entries by the same plate within the window that are flagged suspicious",
    "suspicious_window_minutes": "Window for repeated entry detection",
    "max_parking_hours": "Sessions longer than this raise an overstay alert",
    "capacity_alerts_enabled": "Raise alerts when categories reach their threshold / capacity",
    "detection_retention_days": "Raw detections (not transactions) older than this are purged",
}

_cache: dict = {}
_cache_time = 0.0
_lock = threading.Lock()
CACHE_TTL = 5.0


def get_all(db: Session) -> dict:
    global _cache, _cache_time
    with _lock:
        if time.monotonic() - _cache_time < CACHE_TTL and _cache:
            return dict(_cache)
        values = dict(DEFAULTS)
        for row in db.query(SystemSetting).all():
            if row.key in DEFAULTS:
                values[row.key] = row.value
        _cache, _cache_time = values, time.monotonic()
        return dict(values)


def get(db: Session, key: str):
    return get_all(db).get(key, DEFAULTS.get(key))


def update(db: Session, changes: dict) -> dict:
    global _cache_time
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise KeyError(key)
        expected = type(DEFAULTS[key])
        if expected is float and isinstance(value, int):
            value = float(value)
        if expected is int and isinstance(value, float) and value.is_integer():
            value = int(value)
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            raise ValueError(f"{key} must be {expected.__name__}")
        row = db.get(SystemSetting, key)
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    db.flush()
    with _lock:
        _cache_time = 0.0
    return get_all(db)


def invalidate():
    global _cache_time
    with _lock:
        _cache_time = 0.0
