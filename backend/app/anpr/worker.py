"""One worker thread per camera: capture -> detect -> track -> count."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import cv2
import numpy as np

from ..config import settings
from ..database import SessionLocal
from ..models import AlertType, Camera, CameraStatus, Direction, Severity
from ..services import events
from ..services.alerts import create_alert
from ..services.counting import DetectionEvent, process_detection
from .engine import ANPREngine
from .simulator import SimulatedSource
from .sources import OpenCVSource, SourceError, build_stream_url, redact_url
from .tracker import DEFAULT_ZONE, VehicleTracker

log = logging.getLogger("anpr.worker")


class CameraWorker(threading.Thread):
    def __init__(self, camera_id: int):
        super().__init__(daemon=True, name=f"camera-{camera_id}")
        self.camera_id = camera_id
        self._stop_evt = threading.Event()
        self._jpeg: bytes | None = None
        self._jpeg_lock = threading.Lock()
        self._frame_cond = threading.Condition()
        self.status = CameraStatus.CONNECTING
        self.last_error: str | None = None
        self.fps = 0.0
        self.frames = 0
        self.events = 0
        self.last_event: dict | None = None
        self.reconnects = 0
        self.engine_mode = "pending"
        self._was_online = False
        self._offline_alerted = False
        self._cfg: dict = {}
        self._cfg_loaded = 0.0
        self.tracker = VehicleTracker()
        self.tracker.prefix = f"C{camera_id}-"

    # ---------------------------------------------------------------- api
    def stop(self):
        self._stop_evt.set()

    def latest_jpeg(self) -> bytes | None:
        with self._jpeg_lock:
            return self._jpeg

    def wait_frame(self, timeout: float = 2.0) -> bytes | None:
        with self._frame_cond:
            self._frame_cond.wait(timeout)
        return self.latest_jpeg()

    def runtime(self) -> dict:
        return {
            "status": self.status,
            "fps": round(self.fps, 1),
            "frames": self.frames,
            "events": self.events,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
            "engine": self.engine_mode,
            "active_tracks": len(self.tracker.active_tracks()),
            "last_event": self.last_event,
        }

    # -------------------------------------------------------------- config
    def _load_config(self, force=False) -> dict | None:
        if not force and time.monotonic() - self._cfg_loaded < 5:
            return self._cfg
        db = SessionLocal()
        try:
            cam = db.get(Camera, self.camera_id)
            if cam is None:
                return None
            self._cfg = {
                "name": cam.name,
                "code": cam.camera_code,
                "direction": cam.direction,
                "url": build_stream_url(cam.rtsp_url, cam.username, cam.password),
                "is_simulated": cam.is_simulated,
                "is_enabled": cam.is_enabled,
                "zone": cam.detection_zone or DEFAULT_ZONE,
                "vpm": cam.sim_vehicles_per_minute,
            }
            self._cfg_loaded = time.monotonic()
            self.tracker.set_zone(self._cfg["zone"])
            return self._cfg
        finally:
            db.close()

    def _set_status(self, status: str, error: str | None = None):
        changed = status != self.status
        self.status, self.last_error = status, error
        db = SessionLocal()
        try:
            cam = db.get(Camera, self.camera_id)
            if cam is None:
                return
            cam.status = status
            cam.last_error = error
            if status == CameraStatus.ONLINE:
                cam.last_seen_at = datetime.now(timezone.utc)
            if changed:
                if status == CameraStatus.OFFLINE and not self._offline_alerted:
                    title = f"Camera '{cam.name}' disconnected" if self._was_online else f"Camera '{cam.name}' unreachable"
                    create_alert(db, AlertType.CAMERA_OFFLINE, Severity.CRITICAL, title,
                                 error or "Stream lost", camera_id=cam.id, is_simulated=cam.is_simulated, dedupe_seconds=120)
                    self._offline_alerted = True
                elif status == CameraStatus.ONLINE and self._offline_alerted:
                    self._offline_alerted = False
                    create_alert(db, AlertType.CAMERA_ONLINE, Severity.INFO, f"Camera '{cam.name}' connection restored",
                                 f"Reconnected after {self.reconnects} attempt(s).", camera_id=cam.id, is_simulated=cam.is_simulated)
                events.emit(db, "camera_status", {"camera_id": cam.id, "name": cam.name, "status": status, "error": error,
                                                  "is_simulated": cam.is_simulated})
            db.commit()
        except Exception:
            db.rollback()
            log.exception("status update failed")
        finally:
            db.close()

    def _heartbeat(self):
        db = SessionLocal()
        try:
            cam = db.get(Camera, self.camera_id)
            if cam:
                cam.last_seen_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    # ---------------------------------------------------------------- loop
    def run(self):
        backoff = settings.RECONNECT_MIN_SECONDS
        sim_source: SimulatedSource | None = None
        while not self._stop_evt.is_set():
            cfg = self._load_config(force=True)
            if cfg is None or not cfg["is_enabled"]:
                self._set_status(CameraStatus.DISABLED)
                return
            if cfg["is_simulated"]:
                if sim_source is None:
                    sim_source = SimulatedSource(self.camera_id, cfg["direction"], cfg["vpm"], SessionLocal,
                                                 settings.SIM_DISCONNECT_PROBABILITY)
                source = sim_source
            else:
                source = OpenCVSource(cfg["url"])
            try:
                if self.status != CameraStatus.ONLINE:
                    self._set_status(CameraStatus.CONNECTING, self.last_error)
                source.open()
                self._set_status(CameraStatus.ONLINE)
                self._was_online = True
                backoff = settings.RECONNECT_MIN_SECONDS
                self._stream_loop(source)
            except SourceError as e:
                self.last_error = str(e)
            except Exception as e:  # unexpected - keep the worker alive
                log.exception("camera %s crashed", self.camera_id)
                self.last_error = f"Internal error: {e}"
            finally:
                if not cfg["is_simulated"]:
                    source.close()
            if self._stop_evt.is_set():
                break
            self._set_status(CameraStatus.OFFLINE, self.last_error)
            self._publish_placeholder(f"RECONNECTING in {backoff:.0f}s", self.last_error or "")
            self.reconnects += 1
            self._stop_evt.wait(backoff)
            backoff = min(backoff * 2, settings.RECONNECT_MAX_SECONDS)
        if sim_source:
            sim_source.close()
        self._set_status(CameraStatus.OFFLINE, "Worker stopped")

    def _stream_loop(self, source):
        n = 0
        t0 = time.monotonic()
        last_beat = time.monotonic()
        engine: ANPREngine | None = None
        use_truth = source.is_simulated and not settings.SIM_USE_REAL_ANPR
        if use_truth:
            self.engine_mode = "simulated-ground-truth"
        else:
            engine = ANPREngine.get()
            self.engine_mode = "yolo+paddleocr" if engine.available else f"unavailable: {engine.error}"
        while not self._stop_evt.is_set():
            cfg = self._load_config()
            if cfg is None or not cfg["is_enabled"]:
                self._stop_evt.set()
                break
            frame = source.read()
            n += 1
            self.frames += 1
            if time.monotonic() - t0 >= 2:
                self.fps = n / (time.monotonic() - t0)
                n, t0 = 0, time.monotonic()
            if time.monotonic() - last_beat > 15:
                self._heartbeat()
                last_beat = time.monotonic()

            dets = None
            if use_truth:
                dets = source.detections()
            elif engine.available and self.frames % max(1, settings.PROCESS_EVERY_N_FRAMES) == 0:
                zone_top = min(p[1] for p in cfg["zone"].get("polygon", DEFAULT_ZONE["polygon"]))
                dets = engine.detect(frame, zone_top)
            if dets is not None:
                for tev in self.tracker.update(dets, frame):
                    self._handle_event(tev, cfg, source.is_simulated)
            self._publish(frame, cfg, source.is_simulated)

    def _handle_event(self, tev, cfg, is_simulated):
        ev = DetectionEvent(
            plate_text=tev.plate_text, plate_confidence=tev.plate_confidence, vehicle_type=tev.vehicle_type,
            vehicle_confidence=tev.vehicle_confidence, track_id=tev.track_id, ocr_reads=tev.ocr_reads,
            vehicle_image=tev.vehicle_crop, plate_image=tev.plate_crop, bbox=tev.bbox, is_simulated=is_simulated,
            direction=cfg["direction"],
        )
        db = SessionLocal()
        try:
            res = process_detection(db, self.camera_id, ev)
            self.events += 1
            self.last_event = {"plate": res.get("plate"), "status": res.get("status"), "at": datetime.now(timezone.utc).isoformat()}
            log.info("[%s] %s %s -> %s", cfg["code"], cfg["direction"], tev.plate_text, res.get("status"))
        except Exception:
            log.exception("failed to process detection")
        finally:
            db.close()

    # ------------------------------------------------------------- stream
    def _publish(self, frame: np.ndarray, cfg: dict, is_simulated: bool):
        img = frame.copy()
        h, w = img.shape[:2]
        zone = cfg["zone"]
        poly = np.array([[int(x * w), int(y * h)] for x, y in zone.get("polygon", DEFAULT_ZONE["polygon"])], np.int32)
        cv2.polylines(img, [poly], True, (255, 200, 0), 2)
        ly = int(float(zone.get("trigger_line", DEFAULT_ZONE["trigger_line"])) * h)
        cv2.line(img, (0, ly), (w, ly), (0, 0, 255) if cfg["direction"] == Direction.EXIT else (0, 200, 0), 2)
        for tr in self.tracker.active_tracks():
            x1, y1, x2, y2 = map(int, tr.bbox)
            color = (0, 255, 0) if tr.emitted else (0, 200, 255) if tr.triggered else (255, 255, 0)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            label = tr.id
            if tr.plate_reads:
                label += f" {tr.plate_reads[-1][0]}"
            if tr.emitted:
                label += " COUNTED"
            cv2.putText(img, label, (x1, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)
        banner = f"{cfg['code']} | {cfg['name']} | {cfg['direction']} | {datetime.now():%Y-%m-%d %H:%M:%S}"
        cv2.rectangle(img, (0, 0), (w, 26), (40, 20, 10), -1)
        cv2.putText(img, banner, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        if is_simulated:
            cv2.putText(img, "SIMULATED", (w - 150, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 140, 255), 2, cv2.LINE_AA)
        self._encode(img)

    def _publish_placeholder(self, title: str, detail: str):
        img = np.full((360, 640, 3), (40, 25, 15), np.uint8)
        cv2.putText(img, title, (30, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (80, 80, 255), 2, cv2.LINE_AA)
        cv2.putText(img, (detail or "")[:70], (30, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA)
        self._encode(img)

    def _encode(self, img: np.ndarray):
        h, w = img.shape[:2]
        if w > settings.STREAM_MAX_WIDTH:
            img = cv2.resize(img, (settings.STREAM_MAX_WIDTH, int(h * settings.STREAM_MAX_WIDTH / w)))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, settings.STREAM_JPEG_QUALITY])
        if ok:
            with self._jpeg_lock:
                self._jpeg = buf.tobytes()
            with self._frame_cond:
                self._frame_cond.notify_all()


__all__ = ["CameraWorker", "redact_url"]
