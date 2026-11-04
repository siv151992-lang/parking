"""Adding many cameras at once."""
import io

import pytest
from openpyxl import Workbook

from app.api.cameras_bulk import parse_position
from app.models import Camera, ParkingRow

from .conftest import login
from .test_rtsp_probe import PASSWORD, USER, camera_port  # noqa: F401  (fake RTSP camera fixture)


def test_parse_position():
    a, b = ParkingRow(id=1, name="Row A", capacity=10), ParkingRow(id=2, name="Basement", capacity=5)
    rows = [a, b]
    assert parse_position("Gate in", rows) == (None, "ENTRY")
    assert parse_position("main gate OUT", rows) == (None, "EXIT")
    assert parse_position("in", rows) == (None, "ENTRY")
    assert parse_position("Row A in", rows) == (a, "ENTRY")
    assert parse_position("a out", rows) == (a, "EXIT")
    assert parse_position("row-a  exit", rows) == (a, "EXIT")
    assert parse_position("Basement entry", rows) == (b, "ENTRY")
    with pytest.raises(ValueError, match="Unknown row"):
        parse_position("Row Z in", rows)
    with pytest.raises(ValueError, match="must end with"):
        parse_position("Row A", rows)


def _rows(client, h):
    client.post("/api/rows", json={"name": "Row A", "capacity": 20}, headers=h)


def test_bulk_check_then_add(client, db):
    h = login(client)
    _rows(client, h)
    cams = [
        {"name": "Gate in", "position": "Gate in", "ip_address": "10.0.0.11"},
        {"name": "Gate out", "position": "gate out", "ip_address": "10.0.0.12", "username": "op", "password": "x"},
        {"name": "Row A in", "position": "Row A in", "ip_address": "10.0.0.21"},
        {"name": "Bad row", "position": "Row Q in", "ip_address": "10.0.0.31"},
        {"name": "No ip", "position": "Gate in"},
        {"name": "Dup", "position": "Row A out", "ip_address": "10.0.0.21"},
    ]
    body = {"cameras": cams, "default_username": "admin", "default_password": "secret", "check_connection": False}
    r = client.post("/api/cameras/bulk", json={**body, "dry_run": True}, headers=h).json()
    assert (r["valid"], r["invalid"]) == (3, 3)
    assert [l["camera_code"] for l in r["lines"][:3]] == ["CAM-EN-01", "CAM-EX-01", "CAM-ROWA-EN-01"]
    assert "Unknown row" in r["lines"][3]["errors"][0]
    assert r["lines"][4]["errors"] == ["IP address is missing"]
    assert "used twice" in r["lines"][5]["errors"][0]
    assert all("password" not in l for l in r["lines"])
    assert db.query(Camera).count() == 0                     # a check saves nothing

    r = client.post("/api/cameras/bulk", json={**body, "dry_run": False}, headers=h).json()
    assert r["created"] == 3 and r["skipped"] == 3
    db.expire_all()
    by_name = {c.name: c for c in db.query(Camera).all()}
    assert by_name["Gate in"].username == "admin" and by_name["Gate in"].password == "secret"
    assert by_name["Gate out"].username == "op" and by_name["Gate out"].direction == "EXIT"
    assert by_name["Row A in"].row_id is not None
    assert by_name["Gate in"].rtsp_url == "rtsp://10.0.0.11/Streaming/Channels/101"
    # adding the same list again: every camera is already there
    r = client.post("/api/cameras/bulk", json={**body, "dry_run": True}, headers=h).json()
    assert r["lines"][0]["errors"] == ["This camera is already added"]


def test_bulk_connection_check_finds_video_address(client, camera_port):  # noqa: F811
    h = login(client)
    r = client.post("/api/cameras/bulk", headers=h, json={"dry_run": True, "check_connection": True, "cameras": [
        {"name": "ok", "position": "gate in", "ip_address": f"127.0.0.1:{camera_port}", "username": USER, "password": PASSWORD},
        {"name": "bad login", "position": "gate out", "rtsp_url": f"rtsp://127.0.0.1:{camera_port}/live/main", "username": USER, "password": "no"},
    ]}).json()
    ok, bad = r["lines"]
    assert ok["connection"] == "ok" and ok["rtsp_url"] == f"rtsp://127.0.0.1:{camera_port}/live/main"
    assert bad["connection"] == "auth" and "Wrong username or password" in bad["warnings"][0]
    assert r["valid"] == 2                                   # connection problems are warnings, not errors


def test_parse_excel_and_csv(client):
    h = login(client)
    wb = Workbook()
    ws = wb.active
    ws.append(["Name", "Position", "IP address", "Username", "Password"])
    ws.append(["Gate in", "Gate in", "10.0.0.11", "admin", 12345])
    ws.append([None, None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/cameras/bulk/parse-file", headers=h,
                    files={"file": ("cams.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.json()["rows"] == [["Name", "Position", "IP address", "Username", "Password"], ["Gate in", "Gate in", "10.0.0.11", "admin", "12345"]]
    csv_bytes = "﻿Name;Position;IP address\nRow A in;Row A in;10.0.0.21\n".encode()
    r = client.post("/api/cameras/bulk/parse-file", headers=h, files={"file": ("c.csv", csv_bytes, "text/csv")})
    assert r.json()["rows"][1] == ["Row A in", "Row A in", "10.0.0.21"]
    assert client.post("/api/cameras/bulk/parse-file", headers=h, files={"file": ("c.pdf", b"x", "application/pdf")}).status_code == 400
