from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require
from ..models import Role, User
from ..schemas import UserCreate, UserUpdate
from ..security import PERMISSIONS, hash_password, validate_password_strength
from ..serializers import user_out
from ..services.audit import audit

router = APIRouter(prefix="/api/users", tags=["User Management"])


@router.get("")
def list_users(q: str = "", db: Session = Depends(get_db), _=Depends(require("users.manage"))):
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.username.ilike(like), User.full_name.ilike(like), User.email.ilike(like)))
    return [user_out(u) for u in query.order_by(User.id).all()]


@router.get("/roles")
def roles(_=Depends(require("users.manage"))):
    return {
        "roles": Role.ALL,
        "permissions": {p: sorted(r) for p, r in PERMISSIONS.items()},
    }


@router.post("", status_code=201)
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db), user=Depends(require("users.manage"))):
    try:
        validate_password_strength(body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if db.query(User).filter(or_(User.username == body.username, User.email == body.email)).first():
        raise HTTPException(409, "Username or email already exists")
    u = User(username=body.username, email=body.email, full_name=body.full_name, role=body.role,
             is_active=body.is_active, hashed_password=hash_password(body.password))
    db.add(u)
    db.flush()
    audit(db, user, "CREATE_USER", "user", u.id, {"username": u.username, "role": u.role}, client_ip(request))
    db.commit()
    return user_out(u)


@router.put("/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, db: Session = Depends(get_db), user=Depends(require("users.manage"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_unset=True)
    if u.id == user.id and (changes.get("is_active") is False or (changes.get("role") and changes["role"] != Role.SUPER_ADMIN)):
        raise HTTPException(400, "You cannot deactivate or demote your own account")
    if "password" in changes:
        pw = changes.pop("password")
        if pw:
            try:
                validate_password_strength(pw)
            except ValueError as e:
                raise HTTPException(400, str(e))
            u.hashed_password = hash_password(pw)
            changes["password"] = "changed"
    if "email" in changes and db.query(User).filter(User.email == changes["email"], User.id != u.id).first():
        raise HTTPException(409, "Email already in use")
    for k, v in changes.items():
        if k != "password":
            setattr(u, k, v)
    audit(db, user, "UPDATE_USER", "user", u.id, {k: v for k, v in changes.items()}, client_ip(request))
    db.commit()
    return user_out(u)


@router.delete("/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require("users.manage"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == user.id:
        raise HTTPException(400, "You cannot delete your own account")
    if u.role == Role.SUPER_ADMIN and db.query(User).filter(User.role == Role.SUPER_ADMIN, User.is_active.is_(True)).count() <= 1:
        raise HTTPException(400, "Cannot delete the last super admin")
    audit(db, user, "DELETE_USER", "user", u.id, {"username": u.username}, client_ip(request))
    db.delete(u)
    db.commit()
    return {"ok": True}
