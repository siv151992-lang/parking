"""Password hashing, JWT tokens and role-based permissions."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings
from .models import Role

SA, PM, SO, RV = Role.SUPER_ADMIN, Role.PARKING_MANAGER, Role.SECURITY_OPERATOR, Role.REPORT_VIEWER

# permission -> roles that hold it
PERMISSIONS: dict[str, set[str]] = {
    "dashboard.view": {SA, PM, SO, RV},
    "cameras.view": {SA, PM, SO},
    "cameras.manage": {SA, PM},
    "vehicles.view": {SA, PM, SO, RV},
    "vehicles.manage": {SA, PM},
    "transactions.manual": {SA, PM, SO},
    "transactions.correct": {SA, PM},
    "detections.review": {SA, PM, SO},
    "occupancy.view": {SA, PM, SO, RV},
    "occupancy.manage": {SA, PM},
    "reports.view": {SA, PM, SO, RV},
    "alerts.view": {SA, PM, SO, RV},
    "alerts.manage": {SA, PM, SO},
    "users.manage": {SA},
    "settings.view": {SA, PM},
    "settings.manage": {SA},
    "audit.view": {SA, PM},
}


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


def has_permission(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    """Raise ValueError if the password is too weak."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    checks = [any(c.islower() for c in password), any(c.isupper() for c in password), any(c.isdigit() for c in password)]
    if not all(checks):
        raise ValueError("Password must contain upper-case, lower-case letters and a digit")


def create_access_token(user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
