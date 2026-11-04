import asyncio
import base64
import time
from urllib.parse import urlparse, urlunparse

import cv2
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from ..anpr import onvif, rtsp_probe
from ..anpr.manager import camera_manager
from ..anpr.sources import OpenCVSource, SourceError, build_stream_url
from ..anpr.tracker import DEFAULT_ZONE
from ..config import settings
from ..database import get_db
from ..deps import client_ip, require
from ..models import Camera, CameraStatus, Direction, ParkingRow
from ..schemas import CameraCreate, CameraUpdate, OnvifProbeIn, SimulateDetectionIn, TestStreamIn
from ..serializers import camera_out
from ..services import events
from ..services.audit import audit
from ..services.counting import DetectionEvent, process_detection

router = APIRouter(prefix="/api/cameras", tags=["Cameras"])


def _get(db: Session, cid: int) -> Camera:
    cam = db.get(Camera, cid)
    if not cam:
        raise HTTPException(404, "Camera not found")
    return cam


@router.get("")
def list_cameras(db: Session = Depends(get_db), _=Depends(require("cameras.view"))):
    return [camera_out(c, camera_manager.runtime(c.id)) for c in db.query(Camera).order_by(Camera.id).all()]


@router.get("/{cid}")
def get_camera(cid: int, db: Session = Depends(get_db), _=Depends(require("cameras.view"))):
    c = _get(db, cid)
    return camera_out(c, camera_manager.runtime(c.id))


def _row(db: Session, row_id: int | None) -> ParkingRow | None:
    if row_id is None:
        return None
    row = db.get(ParkingRow, row_id)
    if row is None:
        raise HTTPException(400, "Parking row not found")
    return row


def _next_code(db: Session, direction: str, row: ParkingRow | None, reserved: set[str] | None = None) -> str:
    tag = "EN" if direction == Direction.ENTRY else "EX"
    if row is not None:
        slug = "".join(ch for ch in row.name.upper() if ch.isalnum())[-6:] or str(row.id)
        prefix = f"CAM-{slug}-{tag}-"
    else:
        prefix = f"CAM-{tag}-"
    used = {c for (c,) in db.query(Camera.camera_code).filter(Camera.camera_code.like(prefix + "%")).all()} | (reserved or set())
    n = 1
    while f"{prefix}{n:02d}" in used:
        n += 1
    return f"{prefix}{n:02d}"


def _working_url(rtsp_url: str, username: str, password: str) -> str:
    """If the login works but the stream path is wrong, find the camera's real path."""
    if not rtsp_url.lower().startswith("rtsp://"):
        return rtsp_url
    url = build_stream_url(rtsp_url, username, password)
    if rtsp_probe.probe(url, timeout=3)[0] != "path":
        return rtsp_url
    found = rtsp_probe.find_stream_url(url)
    if not found:
        return rtsp_url
    p = urlparse(found)
    return urlunparse(p._replace(netloc=p.hostname + (f":{p.port}" if p.port else "")))


@router.post("", status_code=201)
def create_camera(body: CameraCreate, request: Request, db: Session = Depends(get_db), user=Depends(require("cameras.manage"))):
    row = _row(db, body.row_id)
    if not body.camera_code.strip():
        body.camera_code = _next_code(db, body.direction, row)
    if db.query(Camera).filter(Camera.camera_code == body.camera_code).first():
        raise HTTPException(409, "Camera ID already exists")
    if not body.is_simulated and not body.rtsp_url:
        raise HTTPException(400, "RTSP URL is required for real cameras")
    if not body.is_simulated:
        body.rtsp_url = _working_url(body.rtsp_url, body.username, body.password or "")
    data = body.model_dump()
    data["password"] = data.get("password") or ""
    data["detection_zone"] = data.get("detection_zone") or DEFAULT_ZONE
    cam = Camera(**data, status=CameraStatus.OFFLINE if body.is_enabled else CameraStatus.DISABLED)
    db.add(cam)
    db.flush()
    audit(db, user, "CREATE_CAMERA", "camera", cam.id, {"code": cam.camera_code, "name": cam.name, "direction": cam.direction,
                                                         "simulated": cam.is_simulated}, client_ip(request))
    db.commit()
    if cam.is_enabled:
        camera_manager.start(cam.id)
    events.emit_now("camera_status", {"camera_id": cam.id, "name": cam.name, "status": cam.status})
    return camera_out(cam, camera_manager.runtime(cam.id))


@router.put("/{cid}")
def update_camera(cid: int, body: CameraUpdate, request: Request, db: Session = Depends(get_db), user=Depends(require("cameras.manage"))):
    cam = _get(db, cid)
    changes = body.model_dump(exclude_unset=True)
    if "camera_code" in changes and db.query(Camera).filter(Camera.camera_code == changes["camera_code"], Camera.id != cid).first():
        raise HTTPException(409, "Camera ID already exists")
    if "password" in changes and not changes["password"]:
        changes.pop("password")  # empty password field = keep existing
    if "camera_code" in changes and not (changes["camera_code"] or "").strip():
        changes.pop("camera_code")
    if "row_id" in changes:
        _row(db, changes["row_id"])
    for k, v in changes.items():
        setattr(cam, k, v)
    if not cam.is_simulated and set(changes) & {"rtsp_url", "username", "password"}:
        fixed = _working_url(cam.rtsp_url, cam.username, cam.password)
        if fixed != cam.rtsp_url:
            cam.rtsp_url = changes["rtsp_url"] = fixed
    if not cam.is_enabled:
        cam.status = CameraStatus.DISABLED
    audit(db, user, "UPDATE_CAMERA", "camera", cam.id,
          {k: ("****" if k == "password" else v) for k, v in changes.items()}, client_ip(request))
    db.commit()
    # connection-relevant changes require a restart of the worker
    if set(changes) & {"rtsp_url", "username", "password", "is_simulated", "is_enabled", "direction", "sim_vehicles_per_minute"}:
        camera_manager.restart(cam.id)
    db.refresh(cam)
    return camera_out(cam, camera_manager.runtime(cam.id))


@router.delete("/{cid}")
def delete_camera(cid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("cameras.manage"))):
    cam = _get(db, cid)
    camera_manager.stop(cid)
    audit(db, user, "DELETE_CAMERA", "camera", cid, {"code": cam.camera_code, "name": cam.name}, client_ip(request))
    db.delete(cam)
    db.commit()
    return {"ok": True}


@router.post("/{cid}/restart")
def restart_camera(cid: int, request: Request, db: Session = Depends(get_db), user=Depends(require("cameras.manage"))):
    cam = _get(db, cid)
    audit(db, user, "RESTART_CAMERA", "camera", cid, {}, client_ip(request))
    db.commit()
    camera_manager.restart(cam.id)
    return {"ok": True}


@router.get("/{cid}/stream")
def stream(cid: int, db: Session = Depends(get_db), _=Depends(require("cameras.view", allow_query_token=True))):
    """MJPEG live stream with detection overlay. Use as <img src=...?token=JWT>."""
    _get(db, cid)
    db.close()  # give the DB connection back now: the stream can stay open for hours
    worker = camera_manager.get(cid)
    if worker is None:
        raise HTTPException(409, "Camera worker not running (camera disabled?)")

    async def gen():
        # async: a viewer does not hold one of the server's worker threads
        last = None
        idle_since = time.monotonic()
        period = 1.0 / max(0.5, settings.STREAM_FPS)
        while worker.is_alive():
            worker.touch_viewer()
            frame = worker.latest_jpeg()
            if frame is None or frame is last:
                if time.monotonic() - idle_since > 60:
                    break
                await asyncio.sleep(period / 2)
                continue
            idle_since = time.monotonic()
            last = frame
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
            await asyncio.sleep(period)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-cache, private", "X-Accel-Buffering": "no"})


@router.get("/{cid}/snapshot")
def snapshot(cid: int, db: Session = Depends(get_db), _=Depends(require("cameras.view", allow_query_token=True))):
    _get(db, cid)
    worker = camera_manager.get(cid)
    if worker is None:
        raise HTTPException(404, "No frame available yet")
    idle = time.monotonic() > worker._viewer_until
    worker.touch_viewer()
    frame = worker.wait_frame(timeout=1.0) if idle else worker.latest_jpeg()  # first look: wait for a fresh frame
    frame = frame or worker.latest_jpeg()
    if frame is None:
        raise HTTPException(404, "No frame available yet")
    return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/test-stream")
def test_stream(body: TestStreamIn, db: Session = Depends(get_db), _=Depends(require("cameras.manage"))):
    """Try to connect to an RTSP URL and return a snapshot (does not save anything)."""
    password = body.password
    if not password and body.camera_id:
        cam = db.get(Camera, body.camera_id)
        password = cam.password if cam else ""
    url = build_stream_url(body.rtsp_url, body.username, password)
    found_url = None
    if url.lower().startswith("rtsp://") and rtsp_probe.probe(url)[0] == "path":
        # The login works but the path is wrong: look for the camera's real stream path.
        found = rtsp_probe.find_stream_url(url)
        if not found:
            return {"ok": False, "error": "Login OK, but none of the usual stream paths work on this camera. "
                                          "Enter the RTSP URL from the camera's manual (brand: Other)."}
        url = found
        p = urlparse(found)
        found_url = urlunparse(p._replace(netloc=p.hostname + (f":{p.port}" if p.port else "")))
    src = OpenCVSource(url, read_timeout=8)
    try:
        src.open()
        frame = src.read()
        h, w = frame.shape[:2]
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return {"ok": True, "width": w, "height": h, "fps": round(src.fps, 1), "rtsp_url": found_url,
                "snapshot": "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else None}
    except SourceError as e:
        return {"ok": False, "error": str(e), "rtsp_url": found_url}
    finally:
        src.close()


@router.post("/onvif/discover")
def onvif_discover(_=Depends(require("cameras.manage"))):
    try:
        return {"devices": onvif.discover()}
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/onvif/probe")
def onvif_probe(body: OnvifProbeIn, _=Depends(require("cameras.manage"))):
    try:
        return {"profiles": onvif.get_stream_uris(body.ip_address, body.onvif_port, body.username, body.password)}
    except RuntimeError as e:
        raise HTTPException(501, str(e))
    except Exception as e:  # network / auth errors from the device
        raise HTTPException(502, f"ONVIF query failed: {e}")


@router.post("/inject-detection")
def inject_detection(body: SimulateDetectionIn, request: Request, db: Session = Depends(get_db), user=Depends(require("cameras.manage"))):
    """Testing tool: push one SIMULATED vehicle pass through a camera's counting pipeline."""
    cam = _get(db, body.camera_id)
    ev = DetectionEvent(plate_text=body.plate_number, plate_confidence=body.plate_confidence if body.plate_number else 0.0,
                        vehicle_type=body.vehicle_type, vehicle_confidence=0.95, is_simulated=True, direction=cam.direction,
                        track_id=f"inject-{int(time.time() * 1000)}", ocr_reads=1)
    result = process_detection(db, cam.id, ev)
    audit(db, user, "INJECT_DETECTION", "camera", cam.id, {"plate": body.plate_number, "result": result.get("status")}, client_ip(request))
    db.commit()
    return result
