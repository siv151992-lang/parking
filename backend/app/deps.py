"""Common FastAPI dependencies: authentication and permission checks."""
import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_token, has_permission

bearer = HTTPBearer(auto_error=False)


def _user_from_token(token: str | None, db: Session) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    return user


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    return _user_from_token(creds.credentials if creds else None, db)


def get_user_header_or_query(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
) -> User:
    """For <img>/<video> resources that cannot send headers (MJPEG, media files)."""
    return _user_from_token(creds.credentials if creds else token, db)


def require(permission: str, allow_query_token: bool = False):
    base = get_user_header_or_query if allow_query_token else get_current_user

    def checker(user: User = Depends(base)) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission}")
        return user

    return checker


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
