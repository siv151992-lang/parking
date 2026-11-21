import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, get_current_user
from ..models import User
from ..schemas import ChangePasswordIn, LoginIn
from ..security import DUMMY_HASH, create_access_token, hash_password, validate_password_strength, verify_password
from ..serializers import user_out
from ..services.audit import audit
from ..services.timeutil import ensure_aware, utcnow
from .users import owner_id

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
MAX_ATTEMPTS = 5          # failed logins per account before it is locked
LOCK_MINUTES = 15
IP_MAX_FAILURES = 30      # failed logins per client address (any username) per window
IP_WINDOW_SECONDS = 15 * 60
# Well-known initial password: logging in with it forces a password change.
DEFAULT_PASSWORDS = {"Admin@123"}

_ip_failures: dict[str, deque] = defaultdict(deque)
_ip_lock = threading.Lock()


def _ip_blocked(ip: str | None) -> bool:
    now = time.monotonic()
    with _ip_lock:
        q = _ip_failures[ip or "?"]
        while q and now - q[0] > IP_WINDOW_SECONDS:
            q.popleft()
        return len(q) >= IP_MAX_FAILURES


def _ip_failed(ip: str | None):
    with _ip_lock:
        _ip_failures[ip or "?"].append(time.monotonic())


def _user_payload(db: Session, user: User) -> dict:
    return {**user_out(user), "is_owner": user.id == owner_id(db), "must_change_password": user.must_change_password}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if _ip_blocked(ip):
        raise HTTPException(429, "Too many failed logins from this address. Try again in 15 minutes.")
    # usernames are often email addresses: match them without regard to letter case
    user = db.query(User).filter(func.lower(User.username) == body.username.strip().lower()).first()
    if user and user.locked_until and ensure_aware(user.locked_until) > utcnow():
        raise HTTPException(423, "Account temporarily locked after repeated failed logins. Try again later.")
    # always one bcrypt check, so the response time does not reveal whether the username exists
    ok = verify_password(body.password, user.hashed_password if user else DUMMY_HASH) and user is not None
    if not ok:
        _ip_failed(ip)
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_ATTEMPTS:
                user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
                user.failed_login_attempts = 0
                audit(db, user, "ACCOUNT_LOCKED", "user", user.id, {}, ip)
        audit(db, None, "LOGIN_FAILED", "user", None, {"username": body.username[:64]}, ip)
        db.commit()
        raise HTTPException(401, "Invalid username or password")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    if body.password in DEFAULT_PASSWORDS:
        user.must_change_password = True
    audit(db, user, "LOGIN", "user", user.id, {}, ip)
    db.commit()
    return {"access_token": create_access_token(user.id, user.username, user.role), "token_type": "bearer",
            "user": _user_payload(db, user)}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_payload(db, user)


@router.post("/media-token")
def media_token(user: User = Depends(get_current_user)):
    """Short-lived token for <img> URLs (vehicle images, live video). It cannot call the API."""
    return {"token": create_access_token(user.id, user.username, user.role, typ="media"), "expires_in": 3600}


@router.post("/logout")
def logout(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit(db, user, "LOGOUT", "user", user.id, {}, client_ip(request))
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Change your own password. Every other session of this account is signed out;
    the response carries a new token for this one."""
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(400, "Current password is incorrect")
    if body.new_password == body.current_password or body.new_password in DEFAULT_PASSWORDS:
        raise HTTPException(400, "Choose a new password that is different from the current one")
    try:
        validate_password_strength(body.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    user.hashed_password = hash_password(body.new_password)
    user.must_change_password = False
    user.tokens_valid_after = utcnow().replace(microsecond=0)
    audit(db, user, "CHANGE_PASSWORD", "user", user.id, {}, client_ip(request))
    db.commit()
    return {"ok": True, "access_token": create_access_token(user.id, user.username, user.role), "user": _user_payload(db, user)}
