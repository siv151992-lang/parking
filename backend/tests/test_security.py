"""Security behaviour: tokens, default password, headers, exports, credentials in URLs."""
import time

from app.models import Camera, User
from app.security import hash_password
from app.services.reports import safe_cell, to_pdf

from .conftest import ADMIN_PW, login


def test_default_password_must_be_changed(client, db):
    db.add(User(username="boss", email="b@x.io", role="SUPER_ADMIN", hashed_password=hash_password("Admin@123")))
    db.commit()
    r = client.post("/api/auth/login", json={"username": "boss", "password": "Admin@123"})
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/dashboard/stats", headers=h).json()["detail"] == "PASSWORD_CHANGE_REQUIRED"
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert client.post("/api/auth/change-password", headers=h,
                       json={"current_password": "Admin@123", "new_password": "Admin@123"}).status_code == 400
    r = client.post("/api/auth/change-password", headers=h, json={"current_password": "Admin@123", "new_password": "N3w-Secret-pw"})
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is False
    new_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/dashboard/stats", headers=new_h).status_code == 200


def test_password_change_ends_other_sessions(client):
    old = login(client)
    time.sleep(1.1)  # tokens carry whole seconds
    r = client.post("/api/auth/change-password", headers=old, json={"current_password": ADMIN_PW, "new_password": "An0ther-pw!"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=old).status_code == 401           # old session ended
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200


def test_media_token_only_opens_media(client):
    h = login(client)
    media = client.post("/api/auth/media-token", headers=h).json()["token"]
    access = h["Authorization"].split()[1]
    # a media token cannot call the API ...
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {media}"}).status_code == 401
    # ... and the full access token is no longer accepted in URLs
    assert client.get(f"/api/media/none.jpg?token={access}").status_code == 401
    assert client.get(f"/api/media/none.jpg?token={media}").status_code == 404  # authenticated, file missing
    for path in ("%2e%2e/%2e%2e/app/config.py", "..%2f..%2fapp%2fconfig.py", "%2e%2e%2f.secret_key"):
        assert client.get(f"/api/media/{path}", headers=h).status_code == 404   # no path traversal


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_ip_login_limit(client):
    from app.api import auth
    auth._ip_failures.clear()
    for _ in range(auth.IP_MAX_FAILURES):
        assert client.post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW}).status_code == 429
    auth._ip_failures.clear()


def test_export_cells_are_not_formulas():
    assert safe_cell("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert safe_cell("MH12AB1234") == "MH12AB1234" and safe_cell(-5) == -5
    rep = {"title": "T <b>", "facility": "A & B <script>", "subtitle": "s", "generated_at": "now", "summary": {},
           "columns": [{"key": "a", "label": "A"}], "rows": [{"a": "<x>"}], "chart": {}}
    assert to_pdf(rep).startswith(b"%PDF")                                     # markup in names no longer breaks the PDF


def test_camera_url_credentials_are_not_exposed(client, db):
    h = login(client)
    r = client.post("/api/cameras", headers=h, json={"name": "Gate", "direction": "ENTRY", "is_enabled": False,
                                                      "rtsp_url": "rtsp://admin:s3cret@10.0.0.5:554/Streaming/Channels/101"})
    assert r.status_code == 201, r.text
    assert "s3cret" not in r.text and r.json()["rtsp_url"] == "rtsp://10.0.0.5:554/Streaming/Channels/101"
    cam = db.get(Camera, r.json()["id"])
    assert (cam.username, cam.password) == ("admin", "s3cret")
    logs = client.get("/api/audit-logs", headers=h).text
    assert "s3cret" not in logs
