"""RTSP diagnostics against a fake camera that uses Digest authentication."""
import hashlib
import re
import socket
import threading

import pytest

from app.anpr.rtsp_probe import diagnose, find_stream_url
from .conftest import login

REALM, NONCE, USER, PASSWORD, PATH = "IP Camera", "abc123", "admin", "p@ss#1", "/live/main"


def _md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def _handle(conn):
    with conn:
        buf = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
            while b"\r\n\r\n" in buf:
                req, buf = buf.split(b"\r\n\r\n", 1)
                text = req.decode()
                uri = text.split(" ")[1]
                cseq = re.search(r"CSeq: (\d+)", text).group(1)
                auth = re.search(r"Authorization: Digest (.*)", text)
                ok = False
                if auth:
                    p = dict(re.findall(r'(\w+)="([^"]*)"', auth.group(1)))
                    ha1 = _md5(f"{p['username']}:{REALM}:{PASSWORD}") if p["username"] == USER else ""
                    ok = p["response"] == _md5(f"{ha1}:{NONCE}:{_md5('DESCRIBE:' + p['uri'])}")
                if not ok:
                    resp = f'RTSP/1.0 401 Unauthorized\r\nCSeq: {cseq}\r\nWWW-Authenticate: Digest realm="{REALM}", nonce="{NONCE}"\r\n\r\n'
                elif uri.endswith(PATH):
                    resp = f"RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\nContent-Length: 0\r\n\r\n"
                else:
                    resp = f"RTSP/1.0 404 Not Found\r\nCSeq: {cseq}\r\n\r\n"
                conn.sendall(resp.encode())


@pytest.fixture(scope="module")
def camera_port():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=_handle, args=(conn,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    yield srv.getsockname()[1]
    srv.close()


def url(port, user=None, pw=None, path=PATH):
    from app.anpr.sources import build_stream_url
    return build_stream_url(f"rtsp://127.0.0.1:{port}{path}", user or "", pw or "")


def test_correct_login_and_path(camera_port):
    assert diagnose(url(camera_port, USER, PASSWORD)) is None


def test_wrong_password(camera_port):
    assert "Wrong username or password" in diagnose(url(camera_port, USER, "nope"))


def test_missing_credentials(camera_port):
    assert "requires a username and password" in diagnose(url(camera_port))


def test_wrong_path(camera_port):
    assert "does not exist" in diagnose(url(camera_port, USER, PASSWORD, "/Streaming/Channels/101"))


def test_finds_the_real_path(camera_port):
    found = find_stream_url(url(camera_port, USER, PASSWORD, "/Streaming/Channels/101"))
    assert found and found.endswith("/live/main")
    assert find_stream_url(url(camera_port, USER, "nope")) is None


def test_test_stream_reports_found_path(client, camera_port):
    h = login(client)
    r = client.post("/api/cameras/test-stream", headers=h, json={
        "rtsp_url": f"rtsp://127.0.0.1:{camera_port}/Streaming/Channels/101", "username": USER, "password": PASSWORD})
    # the fake camera sends no video, so the open fails, but the right path is reported without credentials
    assert r.json()["rtsp_url"] == f"rtsp://127.0.0.1:{camera_port}/live/main"


def test_closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert "refused port" in diagnose(f"rtsp://127.0.0.1:{port}/x")


def test_not_rtsp():
    assert diagnose("/data/video.mp4") is None
