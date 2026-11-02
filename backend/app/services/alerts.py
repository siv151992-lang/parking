"""Alert creation; each alert is pushed to dashboards after commit."""
from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import Alert
from . import events
from .timeutil import utcnow


def serialize_alert(a: Alert) -> dict:
    return {
        "id": a.id,
        "alert_type": a.alert_type,
        "severity": a.severity,
        "title": a.title,
        "message": a.message,
        "camera_id": a.camera_id,
        "session_id": a.session_id,
        "detection_id": a.detection_id,
        "plate_number": a.plate_number,
        "data": a.data or {},
        "is_simulated": a.is_simulated,
        "is_read": a.is_read,
        "is_resolved": a.is_resolved,
        "resolved_at": a.resolved_at,
        "created_at": a.created_at,
    }


def create_alert(
    db: Session,
    alert_type: str,
    severity: str,
    title: str,
    message: str = "",
    *,
    camera_id: int | None = None,
    session_id: int | None = None,
    detection_id: int | None = None,
    plate_number: str | None = None,
    data: dict | None = None,
    is_simulated: bool = False,
    dedupe_seconds: int = 0,
) -> Alert | None:
    """Create an alert. With dedupe_seconds, an identical unresolved alert
    (same type/camera/plate) inside that window suppresses the new one."""
    if dedupe_seconds:
        q = db.query(Alert).filter(
            Alert.alert_type == alert_type,
            Alert.is_resolved.is_(False),
            Alert.created_at >= utcnow() - timedelta(seconds=dedupe_seconds),
        )
        q = q.filter(Alert.camera_id == camera_id) if camera_id else q
        q = q.filter(Alert.plate_number == plate_number) if plate_number else q
        if q.first():
            return None
    alert = Alert(
        alert_type=alert_type,
        severity=severity,
        title=title,
        message=message,
        camera_id=camera_id,
        session_id=session_id,
        detection_id=detection_id,
        plate_number=plate_number,
        data=data or {},
        is_simulated=is_simulated,
    )
    db.add(alert)
    db.flush()
    events.emit(db, "alert", serialize_alert(alert))
    return alert
