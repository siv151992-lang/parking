"""REST API, RBAC, reports export and WebSocket."""
from app.models import Role

from .conftest import login, make_user


def test_login_and_me(client):
    h = login(client)
    r = client.get("/api/auth/me", headers=h)
    assert r.status_code == 200 and r.json()["role"] == "SUPER_ADMIN"


def test_bad_login_and_lockout(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "Admin@123"}).status_code == 423


def test_requires_auth(client):
    assert client.get("/api/dashboard/stats").status_code == 401


def test_rbac(client, db):
    make_user(db, "viewer1", Role.REPORT_VIEWER)
    make_user(db, "op1", Role.SECURITY_OPERATOR)
    hv = login(client, "viewer1", "Passw0rd!")
    ho = login(client, "op1", "Passw0rd!")
    cam = {"camera_code": "C1", "name": "Cam", "direction": "ENTRY", "is_simulated": True, "is_enabled": False}
    assert client.post("/api/cameras", json=cam, headers=hv).status_code == 403
    assert client.post("/api/cameras", json=cam, headers=ho).status_code == 403
    assert client.get("/api/reports/hourly", headers=hv).status_code == 200
    assert client.get("/api/users", headers=ho).status_code == 403
    # operator may do manual entry, but not cancel (correction) transactions
    r = client.post("/api/entries/manual", json={"plate_number": "MH12AB1234"}, headers=ho)
    assert r.status_code == 201
    tx = r.json()["transaction"]["id"]
    assert client.post(f"/api/entries/{tx}/cancel", json={"reason": "test"}, headers=ho).status_code == 403
    assert client.post(f"/api/entries/{tx}/cancel", json={"reason": "test"}, headers=login(client)).status_code == 200


def test_camera_crud_and_inject(client):
    h = login(client)
    r = client.post("/api/cameras", json={"camera_code": "SIM1", "name": "Sim Entry", "direction": "ENTRY", "is_simulated": True,
                                          "is_enabled": False}, headers=h)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert client.post("/api/cameras", json={"camera_code": "SIM1", "name": "dup", "direction": "ENTRY", "is_simulated": True},
                       headers=h).status_code == 409
    assert client.post("/api/cameras", json={"camera_code": "R1", "name": "real", "direction": "ENTRY"}, headers=h).status_code == 400
    r = client.post("/api/cameras/inject-detection", json={"camera_id": cid, "plate_number": "KA01AB1234"}, headers=h)
    assert r.json()["status"] == "ENTRY_CREATED"
    stats = client.get("/api/dashboard/stats", headers=h).json()
    assert stats["entries_today"] == 1 and stats["vehicles_inside"] == 1 and stats["simulated_entries_today"] == 1
    assert client.put(f"/api/cameras/{cid}", json={"name": "Renamed"}, headers=h).json()["name"] == "Renamed"
    assert client.delete(f"/api/cameras/{cid}", headers=h).status_code == 200


def test_manual_flow_and_history(client):
    h = login(client)
    assert client.post("/api/entries/manual", json={"plate_number": "dl 01 cd 5678", "vehicle_type": "TWO_WHEELER"}, headers=h).status_code == 201
    assert client.post("/api/entries/manual", json={"plate_number": "DL01CD5678"}, headers=h).status_code == 409
    assert client.post("/api/exits/manual", json={"plate_number": "DL01CD5678"}, headers=h).status_code == 201
    hist = client.get("/api/vehicles/history/DL01CD5678", headers=h).json()
    assert hist["stats"]["visits"] == 1 and len(hist["timeline"]) == 2
    sessions = client.get("/api/sessions?plate=DL01", headers=h).json()
    assert sessions["total"] == 1 and sessions["items"][0]["status"] == "CLOSED"
    assert client.get("/api/occupancy/reconcile", headers=h).json()["is_consistent"]


def test_capacity_update(client):
    h = login(client)
    r = client.put("/api/occupancy/CAR", json={"total_capacity": 10, "alert_threshold_pct": 80}, headers=h)
    car = next(c for c in r.json()["categories"] if c["category"] == "CAR")
    assert car["total_capacity"] == 10


def test_reports_and_exports(client):
    h = login(client)
    client.post("/api/entries/manual", json={"plate_number": "MH12AB1234"}, headers=h)
    types = [t["key"] for t in client.get("/api/reports/types", headers=h).json()]
    assert len(types) == 10
    for t in types:
        r = client.get(f"/api/reports/{t}", headers=h)
        assert r.status_code == 200, (t, r.text)
        assert "rows" in r.json()
        for fmt, magic in (("csv", b"\xef\xbb\xbf"), ("xlsx", b"PK"), ("pdf", b"%PDF")):
            r = client.get(f"/api/reports/{t}/export?format={fmt}", headers=h)
            assert r.status_code == 200, (t, fmt, r.text[:200])
            assert r.content.startswith(magic), (t, fmt)


def test_settings_and_audit(client):
    h = login(client)
    r = client.put("/api/settings", json={"default_cooldown_seconds": 90}, headers=h)
    assert r.status_code == 200
    assert next(s for s in r.json() if s["key"] == "default_cooldown_seconds")["value"] == 90
    assert client.put("/api/settings", json={"nope": 1}, headers=h).status_code == 400
    assert client.put("/api/settings", json={"fuzzy_max_distance": "x"}, headers=h).status_code == 400
    logs = client.get("/api/audit-logs", headers=h).json()
    assert any(l["action"] == "UPDATE_SETTINGS" for l in logs["items"])


def test_user_management(client):
    h = login(client)
    r = client.post("/api/users", json={"username": "mgr", "email": "m@x.io", "password": "weak", "role": "PARKING_MANAGER"}, headers=h)
    assert r.status_code == 400  # weak password
    r = client.post("/api/users", json={"username": "mgr", "email": "m@x.io", "password": "Strong123", "role": "PARKING_MANAGER"}, headers=h)
    assert r.status_code == 201
    uid = r.json()["id"]
    assert "cameras.manage" in r.json()["permissions"]
    assert client.put(f"/api/users/{uid}", json={"is_active": False}, headers=h).json()["is_active"] is False
    assert client.post("/api/auth/login", json={"username": "mgr", "password": "Strong123"}).status_code == 403


def test_websocket_receives_entry_event(client):
    h = login(client)
    token = h["Authorization"].split()[1]
    with client.websocket_connect(f"/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post("/api/entries/manual", json={"plate_number": "MH12AB1234"}, headers=h)
        types = set()
        for _ in range(2):
            types.add(ws.receive_json()["type"])
        assert {"entry", "occupancy"} <= types


def test_websocket_rejects_bad_token(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=bad") as ws:
            ws.receive_json()
