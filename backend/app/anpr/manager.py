"""Supervises camera worker threads (start / stop / restart on config change)."""
import logging
import threading

from ..database import SessionLocal
from ..models import Camera, CameraStatus
from .worker import CameraWorker

log = logging.getLogger("anpr.manager")


class CameraManager:
    def __init__(self):
        self.workers: dict[int, CameraWorker] = {}
        self._lock = threading.Lock()

    def start_all(self):
        db = SessionLocal()
        try:
            cams = db.query(Camera).all()
            for cam in cams:
                if cam.is_enabled:
                    self.start(cam.id)
                else:
                    cam.status = CameraStatus.DISABLED
            db.commit()
        finally:
            db.close()

    def start(self, camera_id: int):
        with self._lock:
            w = self.workers.get(camera_id)
            if w and w.is_alive():
                return
            w = CameraWorker(camera_id)
            self.workers[camera_id] = w
            w.start()
            log.info("started worker for camera %s", camera_id)

    def stop(self, camera_id: int, join: bool = True):
        with self._lock:
            w = self.workers.pop(camera_id, None)
        if w:
            w.stop()
            if join:
                w.join(timeout=5)

    def restart(self, camera_id: int):
        self.stop(camera_id)
        db = SessionLocal()
        try:
            cam = db.get(Camera, camera_id)
            enabled = cam is not None and cam.is_enabled
            if cam is not None and not enabled:
                cam.status = CameraStatus.DISABLED
                db.commit()
        finally:
            db.close()
        if enabled:
            self.start(camera_id)

    def stop_all(self):
        for cid in list(self.workers):
            self.stop(cid, join=False)
        for w in list(self.workers.values()):
            w.join(timeout=3)

    def get(self, camera_id: int) -> CameraWorker | None:
        return self.workers.get(camera_id)

    def runtime(self, camera_id: int) -> dict:
        w = self.workers.get(camera_id)
        return w.runtime() if w else {"status": "STOPPED"}


camera_manager = CameraManager()
