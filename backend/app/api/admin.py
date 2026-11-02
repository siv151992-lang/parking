from datetime import date
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import client_ip, require
from ..models import AuditLog
from ..services import settings_store
from ..services.audit import audit
from ..services.timeutil import range_bounds

router = APIRouter(prefix="/api", tags=["Settings, Audit & Media"])


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    values = settings_store.get_all(db)
    return [{"key": k, "value": values[k], "default": settings_store.DEFAULTS[k], "description": settings_store.DESCRIPTIONS.get(k, ""),
             "type": type(settings_store.DEFAULTS[k]).__name__} for k in settings_store.DEFAULTS]


@router.put("/settings")
def update_settings(request: Request, changes: dict = Body(...), db: Session = Depends(get_db), user=Depends(require("settings.manage"))):
    if "timezone" in changes:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(changes["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(400, "Unknown timezone")
    try:
        settings_store.update(db, changes)
    except KeyError as e:
        raise HTTPException(400, f"Unknown setting {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit(db, user, "UPDATE_SETTINGS", "settings", None, changes, client_ip(request))
    db.commit()
    settings_store.invalidate()
    return get_settings(db)


@router.get("/audit-logs")
def audit_logs(q: str = "", action: str = "", start: date | None = None, end: date | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
               db: Session = Depends(get_db), _=Depends(require("audit.view"))):
    query = db.query(AuditLog)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(AuditLog.username.ilike(like), AuditLog.entity_id.ilike(like), AuditLog.action.ilike(like)))
    if action:
        query = query.filter(AuditLog.action == action)
    if start or end:
        s, e = range_bounds(db, start or end, end or start)
        query = query.filter(AuditLog.created_at >= s, AuditLog.created_at < e)
    total = query.count()
    rows = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [
        {"id": r.id, "username": r.username, "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id,
         "details": r.details, "ip_address": r.ip_address, "created_at": r.created_at} for r in rows]}


@router.get("/media/{path:path}")
def media(path: str, _=Depends(require("vehicles.view", allow_query_token=True))):
    """Captured vehicle / plate images (authenticated)."""
    base = Path(settings.MEDIA_DIR).resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
