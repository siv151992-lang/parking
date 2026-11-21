"""Common FastAPI dependencies: authentication and permission checks."""
import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_token, has_permission
from .services.timeutil import ensure_aware

bearer = HTTPBearer(auto_error=False)


# Endpoints a user who must change the default password can still use.
PASSWORD_CHANGE_ALLOWED = {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout"}


def user_from_token(token: str | None, db: Session, typ: str = "access") -> User:
    """Validate a JWT of the given type and return its active user."""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from None
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from None
    if payload.get("typ", "access") != typ:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    try:
        user = db.get(User, int(payload["sub"]))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from None
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    if user.tokens_valid_after and int(payload["iat"]) < int(ensure_aware(user.tokens_valid_after).timestamp()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session ended, please log in again")
    return user


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    user = user_from_token(creds.credentials if creds else None, db)
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "PASSWORD_CHANGE_REQUIRED")
    return user


def get_user_header_or_query(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
) -> User:
    """For <img> resources that cannot send headers (MJPEG, media files): the URL may only
    carry a short-lived media token, never the full access token."""
    if creds:
        return get_current_user(request, creds, db)
    user = user_from_token(token, db, typ="media")
    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "PASSWORD_CHANGE_REQUIRED")
    return user


def require(permission: str, allow_query_token: bool = False):
    base = get_user_header_or_query if allow_query_token else get_current_user

    def checker(user: User = Depends(base)) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission}")
        return user

    return checker


def client_ip(request: Request) -> str | None:
    """The connecting client's address. Behind a reverse proxy, uvicorn's --proxy-headers
    (trusted proxies only) already puts the real client here; X-Forwarded-For is not read
    directly because any client could fake it."""
    return request.client.host if request.client else None
