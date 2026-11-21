from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import client_ip, require
from ..models import Role, User
from ..schemas import UserCreate, UserUpdate
from ..security import PERMISSIONS, hash_password, validate_password_strength
from ..serializers import user_out
from ..services.audit import audit
from ..services.timeutil import utcnow

router = APIRouter(prefix="/api/users", tags=["User Management"])


def owner_id(db: Session) -> int | None:
    """The first user ever created is the owner: always an active Super Admin whose
    rights nobody can change. Only the owner grants or removes Super Admin rights."""
    return db.query(func.min(User.id)).scalar()


def _out(db: Session, u: User) -> dict:
    return {**user_out(u), "is_owner": u.id == owner_id(db)}


@router.get("")
def list_users(q: str = "", db: Session = Depends(get_db), _=Depends(require("users.manage"))):
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.username.ilike(like), User.full_name.ilike(like), User.email.ilike(like)))
    oid = owner_id(db)
    return [{**user_out(u), "is_owner": u.id == oid} for u in query.order_by(User.id).all()]


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
    if body.role == Role.SUPER_ADMIN and user.id != owner_id(db):
        raise HTTPException(403, "Only the owner account can create Super Admins")
    if db.query(User).filter(or_(func.lower(User.username) == body.username.lower(),
                                 func.lower(User.email) == body.email.lower())).first():
        raise HTTPException(409, "Username or email already exists")
    u = User(username=body.username, email=body.email, full_name=body.full_name, role=body.role,
             is_active=body.is_active, hashed_password=hash_password(body.password))
    db.add(u)
    db.flush()
    audit(db, user, "CREATE_USER", "user", u.id, {"username": u.username, "role": u.role}, client_ip(request))
    db.commit()
    return _out(db, u)


@router.put("/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, db: Session = Depends(get_db), user=Depends(require("users.manage"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_unset=True)
    oid = owner_id(db)
    if u.id == oid:
        if user.id != oid:
            raise HTTPException(403, "The owner account can only be changed by the owner")
        if ("role" in changes and changes["role"] != Role.SUPER_ADMIN) or changes.get("is_active") is False:
            raise HTTPException(400, "The owner account always stays an active Super Admin")
    elif user.id != oid and (u.role == Role.SUPER_ADMIN or changes.get("role") == Role.SUPER_ADMIN):
        if set(changes) - {"full_name", "email", "password"} or u.role == Role.SUPER_ADMIN:
            raise HTTPException(403, "Only the owner account can change Super Admins or grant Super Admin rights")
    if u.id == user.id and (changes.get("is_active") is False or (changes.get("role") and changes["role"] != Role.SUPER_ADMIN)):
        raise HTTPException(400, "You cannot deactivate or demote your own account")
    if "password" in changes:
        pw = changes.pop("password")
        if pw:
            try:
                validate_password_strength(pw)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
            u.hashed_password = hash_password(pw)
            if u.id != user.id:
                u.tokens_valid_after = utcnow().replace(microsecond=0)  # sign the user out everywhere
            changes["password"] = "changed"
    if "email" in changes and db.query(User).filter(User.email == changes["email"], User.id != u.id).first():
        raise HTTPException(409, "Email already in use")
    for k, v in changes.items():
        if k != "password":
            setattr(u, k, v)
    audit(db, user, "UPDATE_USER", "user", u.id, {k: v for k, v in changes.items()}, client_ip(request))
    db.commit()
    return _out(db, u)


@router.delete("/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require("users.manage"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == owner_id(db):
        raise HTTPException(400, "The owner account cannot be deleted")
    if u.id == user.id:
        raise HTTPException(400, "You cannot delete your own account")
    if u.role == Role.SUPER_ADMIN and user.id != owner_id(db):
        raise HTTPException(403, "Only the owner account can delete Super Admins")
    if u.role == Role.SUPER_ADMIN and db.query(User).filter(User.role == Role.SUPER_ADMIN, User.is_active.is_(True)).count() <= 1:
        raise HTTPException(400, "Cannot delete the last super admin")
    audit(db, user, "DELETE_USER", "user", u.id, {"username": u.username}, client_ip(request))
    db.delete(u)
    db.commit()
    return {"ok": True}
