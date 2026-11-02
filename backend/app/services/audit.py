"""Audit logging for all administrative and manual actions."""
from sqlalchemy.orm import Session

from ..models import AuditLog, User


def audit(
    db: Session,
    user: User | None,
    action: str,
    entity_type: str = "",
    entity_id=None,
    details: dict | None = None,
    ip: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "system",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details or {},
        ip_address=ip,
    )
    db.add(entry)
    return entry
