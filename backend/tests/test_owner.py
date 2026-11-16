"""The first user is the protected owner: always an active Super Admin."""
from app.models import Role, User

from .conftest import login

PW = "Str0ng!Passw0rd"


def test_owner_is_protected(client, db):
    owner = login(client)                                         # admin = first user = owner
    me = client.get("/api/auth/me", headers=owner).json()
    assert me["is_owner"] is True and me["role"] == Role.SUPER_ADMIN
    oid = me["id"]
    # the owner cannot demote / deactivate / delete itself either
    assert client.put(f"/api/users/{oid}", json={"role": "REPORT_VIEWER"}, headers=owner).status_code == 400
    assert client.put(f"/api/users/{oid}", json={"is_active": False}, headers=owner).status_code == 400
    assert client.delete(f"/api/users/{oid}", headers=owner).status_code == 400
    # but can change its own details
    assert client.put(f"/api/users/{oid}", json={"full_name": "Site Owner"}, headers=owner).status_code == 200

    # a second Super Admin, created by the owner
    r = client.post("/api/users", json={"username": "admin2", "email": "a2@x.io", "password": PW, "role": "SUPER_ADMIN"}, headers=owner)
    assert r.status_code == 201 and r.json()["is_owner"] is False
    a2 = login(client, "admin2", PW)
    assert client.get("/api/auth/me", headers=a2).json()["is_owner"] is False
    for change in ({"role": "REPORT_VIEWER"}, {"is_active": False}, {"password": "An0ther!Passw0rd"}, {"email": "x@x.io"}):
        assert client.put(f"/api/users/{oid}", json=change, headers=a2).status_code == 403, change
    assert client.delete(f"/api/users/{oid}", headers=a2).status_code == 400
    # only the owner grants or removes Super Admin rights
    assert client.post("/api/users", json={"username": "admin3", "email": "a3@x.io", "password": PW, "role": "SUPER_ADMIN"},
                       headers=a2).status_code == 403
    mgr = client.post("/api/users", json={"username": "mgr@site.com", "email": "m@x.io", "password": PW, "role": "PARKING_MANAGER"},
                      headers=a2)
    assert mgr.status_code == 201                                  # normal roles are fine
    mid = mgr.json()["id"]
    assert client.put(f"/api/users/{mid}", json={"role": "SUPER_ADMIN"}, headers=a2).status_code == 403
    assert client.put(f"/api/users/{mid}", json={"role": "SECURITY_OPERATOR"}, headers=a2).status_code == 200
    a2_id = r.json()["id"]
    assert client.put(f"/api/users/{a2_id}", json={"role": "REPORT_VIEWER"}, headers=owner).status_code == 200
    assert client.delete(f"/api/users/{a2_id}", headers=owner).status_code == 200


def test_owner_restored_on_start(db):
    from app.main import bootstrap
    owner = db.query(User).order_by(User.id).first()
    owner.role, owner.is_active = Role.REPORT_VIEWER, False       # e.g. changed directly in the database
    db.commit()
    bootstrap()
    db.expire_all()
    owner = db.query(User).order_by(User.id).first()
    assert owner.role == Role.SUPER_ADMIN and owner.is_active
