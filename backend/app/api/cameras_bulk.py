"""Add many cameras at once: from rows pasted out of Excel, or a .xlsx / .csv file.

POST /api/cameras/bulk with dry_run=true checks every line (position, duplicates,
and, optionally, whether the camera answers and accepts the login) without saving.
The same call with dry_run=false adds the valid lines.
"""
import csv
import io
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..anpr import rtsp_probe
from ..anpr.manager import camera_manager
from ..anpr.sources import build_stream_url
from ..anpr.tracker import DEFAULT_ZONE
from ..database import get_db
from ..deps import client_ip, require
from ..models import Camera, CameraStatus, Direction, ParkingRow
from ..services import events
from ..services.audit import audit
from .cameras import _next_code

router = APIRouter(prefix="/api/cameras/bulk", tags=["Cameras"])

MAX_LINES = 500
DEFAULT_PATH = "/Streaming/Channels/101"
IN_WORDS = {"in", "entry", "enter", "entrance", "incoming", "coming in"}
OUT_WORDS = {"out", "exit", "leave", "leaving", "outgoing", "going out"}
GATE_WORDS = {"", "gate", "main gate", "main", "main entrance", "car park", "parking"}


class BulkCamera(BaseModel):
    name: str = ""
    position: str = ""
    ip_address: str = ""
    username: str = ""
    password: str = ""
    rtsp_url: str = ""
    location: str = ""


class BulkIn(BaseModel):
    cameras: list[BulkCamera] = Field(max_length=MAX_LINES)
    default_username: str = ""
    default_password: str = ""
    dry_run: bool = True
    check_connection: bool = True


def parse_position(text: str, rows: list[ParkingRow]) -> tuple[ParkingRow | None, str]:
    """'Gate in', 'main gate out', 'Row A in', 'A out', 'Row B exit' -> (row or None, direction)."""
    t = re.sub(r"[\s·:_\-]+", " ", (text or "").strip().lower()).strip()
    direction = None
    for words, d in ((IN_WORDS, Direction.ENTRY), (OUT_WORDS, Direction.EXIT)):
        for w in sorted(words, key=len, reverse=True):
            if t == w or t.endswith(" " + w):
                direction, t = d, t[: len(t) - len(w)].strip()
                break
        if direction:
            break
    if direction is None:
        raise ValueError("Position must end with 'in' or 'out', e.g. 'Gate in' or 'Row A out'")
    if t in GATE_WORDS:
        return None, direction
    by_name = {r.name.strip().lower(): r for r in rows}
    row = by_name.get(t) or by_name.get(f"row {t}") or by_name.get(t.removeprefix("row ").strip())
    if row is None:
        known = ", ".join(r.name for r in rows) or "none yet"
        raise ValueError(f"Unknown row '{t}'. Add it under Parking Spaces first (rows: {known})")
    return row, direction


def _clean_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse(p._replace(netloc=p.hostname + (f":{p.port}" if p.port else "")))


def check_connection(rtsp_url: str, username: str, password: str) -> dict:
    """Ask the camera directly (no video decoding, so it is quick)."""
    url = build_stream_url(rtsp_url, username, password)
    kind, message = rtsp_probe.probe(url, timeout=3)
    if kind == "path":
        found = rtsp_probe.find_stream_url(url)
        if found:
            return {"connection": "ok", "message": "Camera answers; video address found", "rtsp_url": _clean_url(found)}
        return {"connection": "path", "message": message, "rtsp_url": rtsp_url}
    if kind == "ok":
        return {"connection": "ok", "message": "Camera answers and accepts the login", "rtsp_url": rtsp_url}
    return {"connection": kind, "message": message, "rtsp_url": rtsp_url}


def _validate(db: Session, body: BulkIn) -> list[dict]:
    rows = db.query(ParkingRow).all()
    existing_urls = {c.rtsp_url.strip().lower() for c in db.query(Camera).all() if c.rtsp_url}
    existing_names = {c.name.strip().lower() for c in db.query(Camera).all()}
    seen_urls, seen_names, reserved = set(), set(), set()
    out = []
    for i, c in enumerate(body.cameras, start=1):
        r = {"line": i, "errors": [], "warnings": [], "name": c.name.strip(), "location": c.location.strip(),
             "ip_address": c.ip_address.strip(), "username": (c.username or body.default_username).strip(),
             "password": c.password or body.default_password, "row_id": None, "row": None, "direction": None,
             "position": None, "camera_code": None, "connection": None, "message": None}
        if not r["name"]:
            r["errors"].append("Name is missing")
        elif r["name"].lower() in seen_names:
            r["errors"].append("Same name used twice in this list")
        elif r["name"].lower() in existing_names:
            r["warnings"].append("A camera with this name already exists")
        seen_names.add(r["name"].lower())
        try:
            row, direction = parse_position(c.position, rows)
            r.update(row_id=row.id if row else None, row=row.name if row else None, direction=direction,
                     position=f"{row.name if row else 'Main gate'} · {'in' if direction == Direction.ENTRY else 'out'}")
            r["camera_code"] = _next_code(db, direction, row, reserved)
            reserved.add(r["camera_code"])
        except ValueError as e:
            r["errors"].append(str(e))
        url = c.rtsp_url.strip()
        if not url:
            ip = r["ip_address"]
            if not ip:
                r["errors"].append("IP address is missing")
            elif not re.fullmatch(r"[A-Za-z0-9.\-]+(:\d{1,5})?", ip):
                r["errors"].append(f"'{ip}' is not a valid IP address")
            else:
                url = f"rtsp://{ip}{DEFAULT_PATH}"
        elif not url.lower().startswith("rtsp://"):
            r["errors"].append("RTSP URL must start with rtsp://")
        r["rtsp_url"] = url
        if url:
            if url.lower() in seen_urls:
                r["errors"].append("Same camera address used twice in this list")
            elif url.lower() in existing_urls:
                r["errors"].append("This camera is already added")
            seen_urls.add(url.lower())
        if not r["ip_address"] and url:
            r["ip_address"] = urlparse(url).hostname or ""
        out.append(r)
    return out


@router.post("")
def bulk_cameras(body: BulkIn, request: Request, db: Session = Depends(get_db), user=Depends(require("cameras.manage"))):
    if not body.cameras:
        raise HTTPException(400, "The list is empty")
    lines = _validate(db, body)
    if body.check_connection:
        todo = [r for r in lines if not r["errors"] and r["rtsp_url"]]
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda r: check_connection(r["rtsp_url"], r["username"], r["password"]), todo))
        for r, res in zip(todo, results):
            r.update(connection=res["connection"], message=res["message"], rtsp_url=res["rtsp_url"])
            if res["connection"] != "ok":
                r["warnings"].append(res["message"])
    public = lambda r: {k: v for k, v in r.items() if k != "password"}  # noqa: E731
    valid = [r for r in lines if not r["errors"]]
    if body.dry_run:
        return {"dry_run": True, "lines": [public(r) for r in lines], "valid": len(valid), "invalid": len(lines) - len(valid)}

    created = []
    for r in valid:
        cam = Camera(camera_code=r["camera_code"], name=r["name"], location=r["location"], ip_address=r["ip_address"],
                     port=urlparse(r["rtsp_url"]).port or 554, rtsp_url=r["rtsp_url"], username=r["username"],
                     password=r["password"] or "", direction=r["direction"], row_id=r["row_id"], is_simulated=False,
                     is_enabled=True, detection_zone=DEFAULT_ZONE, status=CameraStatus.OFFLINE)
        db.add(cam)
        db.flush()
        created.append(cam)
        r["id"] = cam.id
    audit(db, user, "BULK_CREATE_CAMERAS", "camera", None,
          {"count": len(created), "codes": [c.camera_code for c in created]}, client_ip(request))
    db.commit()
    for cam in created:
        camera_manager.start(cam.id)
        events.emit_now("camera_status", {"camera_id": cam.id, "name": cam.name, "status": cam.status})
    return {"dry_run": False, "lines": [public(r) for r in lines], "created": len(created), "skipped": len(lines) - len(created)}


@router.post("/parse-file")
async def parse_file(file: UploadFile = File(...), _=Depends(require("cameras.manage"))):
    """Read the first sheet of an .xlsx file, or a .csv / .txt file, into rows of text."""
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "File is larger than 5 MB")
    name = (file.filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        try:
            ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
        except Exception:
            raise HTTPException(400, "Could not read the Excel file")
        rows = [["" if v is None else str(v).strip() for v in row] for row in ws.iter_rows(values_only=True)]
    elif name.endswith((".csv", ".txt")):
        text = data.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = [[v.strip() for v in row] for row in csv.reader(io.StringIO(text), dialect)]
    else:
        raise HTTPException(400, "Upload an .xlsx or .csv file")
    rows = [r for r in rows if any(r)]
    if len(rows) > MAX_LINES + 1:
        raise HTTPException(400, f"At most {MAX_LINES} cameras per file")
    return {"rows": rows}
