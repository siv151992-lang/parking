from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require
from ..models import Alert
from ..services import events
from ..services.alerts import serialize_alert
from ..services.audit import audit
from ..services.timeutil import utcnow

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


@router.get("")
def list_alerts(alert_type: str = "", severity: str = "", resolved: bool | None = None, unread: bool | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                db: Session = Depends(get_db), _=Depends(require("alerts.view"))):
    q = db.query(Alert)
    if alert_type:
        q = q.filter(Alert.alert_type == alert_type)
    if severity:
        q = q.filter(Alert.severity == severity)
    if resolved is not None:
        q = q.filter(Alert.is_resolved.is_(resolved))
    if unread:
        q = q.filter(Alert.is_read.is_(False))
    total = q.count()
    items = q.order_by(Alert.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "unread": db.query(Alert).filter(Alert.is_read.is_(False)).count(),
            "items": [serialize_alert(a) for a in items]}


@router.post("/read-all")
def read_all(db: Session = Depends(get_db), _=Depends(require("alerts.view"))):
    n = db.query(Alert).filter(Alert.is_read.is_(False)).update({Alert.is_read: True})
    db.commit()
    events.emit_now("alerts_read", {"count": n})
    return {"updated": n}


@router.post("/{aid}/read")
def mark_read(aid: int, db: Session = Depends(get_db), _=Depends(require("alerts.view"))):
    a = db.get(Alert, aid)
    if not a:
        raise HTTPException(404, "Alert not found")
    a.is_read = True
    db.commit()
    return serialize_alert(a)


@router.post("/{aid}/resolve")
def resolve(aid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("alerts.manage"))):
    a = db.get(Alert, aid)
    if not a:
        raise HTTPException(404, "Alert not found")
    a.is_resolved = a.is_read = True
    a.resolved_by_id, a.resolved_at = user.id, utcnow()
    audit(db, user, "RESOLVE_ALERT", "alert", a.id, {"type": a.alert_type}, client_ip(request))
    db.commit()
    events.emit_now("alert_updated", serialize_alert(a))
    return serialize_alert(a)
