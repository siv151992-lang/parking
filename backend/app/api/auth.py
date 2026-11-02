from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, get_current_user
from ..models import User
from ..schemas import ChangePasswordIn, LoginIn
from ..security import create_access_token, hash_password, validate_password_strength, verify_password
from ..serializers import user_out
from ..services.audit import audit
from ..services.timeutil import ensure_aware, utcnow

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
MAX_ATTEMPTS = 5
LOCK_MINUTES = 15


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username.strip()).first()
    ip = client_ip(request)
    if user and user.locked_until and ensure_aware(user.locked_until) > utcnow():
        raise HTTPException(423, "Account temporarily locked after repeated failed logins. Try again later.")
    if not user or not verify_password(body.password, user.hashed_password):
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
    audit(db, user, "LOGIN", "user", user.id, {}, ip)
    db.commit()
    return {"access_token": create_access_token(user.id, user.username, user.role), "token_type": "bearer", "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.post("/logout")
def logout(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit(db, user, "LOGOUT", "user", user.id, {}, client_ip(request))
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(400, "Current password is incorrect")
    try:
        validate_password_strength(body.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    user.hashed_password = hash_password(body.new_password)
    audit(db, user, "CHANGE_PASSWORD", "user", user.id, {}, client_ip(request))
    db.commit()
    return {"ok": True}
