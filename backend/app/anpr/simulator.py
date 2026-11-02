"""Camera simulation mode.

Renders a synthetic gate-lane video (vehicles approaching the camera with a
readable number plate) and produces per-frame detections that mimic what
YOLO + OCR return, including realistic noise:
  * OCR confusions (0<->O, 8<->B, ...) on individual frames,
  * occasional unreadable plates and low-confidence reads,
  * vehicles that stop in front of the camera (barrier) - tests duplicate
    prevention,
  * optional random stream drops - tests reconnection and alerts.

EXIT cameras mostly pick plates of vehicles that are currently parked
(simulated sessions), so entries and exits balance like a real facility.
All results produced here are flagged is_simulated=True end to end.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from ..models import Direction, ParkingSession, SessionStatus, VehicleType
from .sources import SourceError
from .tracker import Detection

W, H = 960, 540
STATES = ["MH", "DL", "KA", "TN", "GJ", "RJ", "UP", "WB", "TS", "KL", "HR", "PB", "AP", "MP"]
CONFUSE = {"0": "O", "O": "0", "8": "B", "B": "8", "1": "I", "I": "1", "5": "S", "S": "5", "2": "Z", "6": "G"}
COLORS = [(40, 40, 200), (200, 200, 200), (30, 30, 30), (160, 90, 20), (20, 120, 20), (0, 140, 220), (120, 120, 120), (230, 230, 240)]

# plates currently "on screen" in any simulated camera, so two exit cameras
# don't pick the same parked vehicle at the same time
_inflight: set[str] = set()
_inflight_lock = threading.Lock()


def random_plate(rng: random.Random) -> str:
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return f"{rng.choice(STATES)}{rng.randint(1, 50):02d}{rng.choice(letters)}{rng.choice(letters)}{rng.randint(1, 9999):04d}"


def noisy_read(plate: str, rng: random.Random) -> str:
    chars = list(plate)
    idx = rng.randrange(len(chars))
    chars[idx] = CONFUSE.get(chars[idx], chars[idx])
    return "".join(chars)


@dataclass
class SimVehicle:
    plate: str
    vtype: str
    color: tuple
    progress: float  # 0 (far) .. 1 (near / leaving frame)
    speed: float
    lane_x: float
    stop_at: float | None
    stop_frames: int
    unreadable: bool
    plate_quality: float


class SimulatedSource:
    is_simulated = True

    def __init__(self, camera_id: int, direction: str, vehicles_per_minute: float, session_factory,
                 disconnect_probability_per_min: float = 0.0, fps: float = 12.0, seed: int | None = None):
        self.camera_id = camera_id
        self.direction = direction
        self.vpm = max(0.1, vehicles_per_minute)
        self.session_factory = session_factory
        self.disconnect_p = disconnect_probability_per_min
        self.fps = fps
        self.rng = random.Random(seed if seed is not None else camera_id * 7919 + int(time.time()))
        self.vehicles: list[SimVehicle] = []
        self.frame_no = 0
        self._next_spawn = time.monotonic() + self.rng.uniform(1, 4)
        self._last_frame_t = 0.0
        self._down_until = 0.0
        self._background = self._render_background()
        self._current: list[Detection] = []

    def open(self):
        if time.monotonic() < self._down_until:
            raise SourceError("Simulated camera unreachable (simulated network drop)")

    def close(self):
        with _inflight_lock:
            for v in self.vehicles:
                _inflight.discard(v.plate)

    # ------------------------------------------------------------- spawning
    def _pick_plate(self) -> tuple[str, str]:
        if self.direction == Direction.EXIT and self.rng.random() < 0.9:
            try:
                with self.session_factory() as db:
                    rows = (
                        db.query(ParkingSession.plate_number, ParkingSession.vehicle_type)
                        .filter(ParkingSession.status == SessionStatus.ACTIVE, ParkingSession.is_simulated.is_(True),
                                ParkingSession.plate_number.isnot(None))
                        .order_by(ParkingSession.entry_time)
                        .limit(60)
                        .all()
                    )
                with _inflight_lock:
                    rows = [r for r in rows if r[0] not in _inflight]
                if rows:
                    plate, vtype = self.rng.choice(rows[: max(5, len(rows) // 2)])  # favour older sessions
                    return plate, vtype
            except Exception:
                pass
            if self.rng.random() < 0.85:
                return "", ""  # nothing parked: skip this spawn
        r = self.rng.random()
        vtype = VehicleType.CAR if r < 0.65 else VehicleType.TWO_WHEELER if r < 0.9 else VehicleType.COMMERCIAL
        return random_plate(self.rng), vtype

    def _spawn(self):
        plate, vtype = self._pick_plate()
        if not plate:
            return
        with _inflight_lock:
            if plate in _inflight:
                return
            _inflight.add(plate)
        stops = self.rng.random() < 0.3  # barrier stop: vehicle lingers in front of camera
        self.vehicles.append(
            SimVehicle(
                plate=plate, vtype=vtype, color=self.rng.choice(COLORS), progress=0.0,
                speed=self.rng.uniform(0.012, 0.022), lane_x=self.rng.uniform(0.42, 0.58),
                stop_at=self.rng.uniform(0.55, 0.7) if stops else None, stop_frames=self.rng.randint(30, 70),
                unreadable=self.rng.random() < 0.05, plate_quality=self.rng.uniform(0.7, 1.0),
            )
        )

    # -------------------------------------------------------------- frames
    def read(self) -> np.ndarray:
        now = time.monotonic()
        if now < self._down_until:
            raise SourceError("Simulated stream lost")
        if self.disconnect_p > 0 and self.rng.random() < self.disconnect_p / (60 * self.fps):
            self._down_until = now + self.rng.uniform(8, 20)
            raise SourceError("Simulated stream lost")
        wait = (1.0 / self.fps) - (now - self._last_frame_t)
        if wait > 0:
            time.sleep(wait)
        self._last_frame_t = time.monotonic()
        self.frame_no += 1

        if time.monotonic() >= self._next_spawn and not any(v.progress < 0.35 for v in self.vehicles):
            self._spawn()
            self._next_spawn = time.monotonic() + self.rng.expovariate(self.vpm / 60.0) + 1.5

        frame = self._background.copy()
        dets: list[Detection] = []
        for v in list(self.vehicles):
            if v.stop_at is not None and v.progress >= v.stop_at and v.stop_frames > 0:
                v.stop_frames -= 1
            else:
                v.progress += v.speed
            if v.progress > 1.08:
                self.vehicles.remove(v)
                with _inflight_lock:
                    _inflight.discard(v.plate)
                continue
            det = self._draw_vehicle(frame, v)
            if det:
                dets.append(det)
        self._current = dets
        return frame

    def detections(self) -> list[Detection]:
        """Ground-truth detections for the frame returned by the last read()."""
        return self._current

    def _render_background(self) -> np.ndarray:
        img = np.full((H, W, 3), (70, 74, 78), np.uint8)
        cv2.rectangle(img, (0, 0), (W, int(H * 0.18)), (150, 120, 90), -1)  # building / sky
        road = np.array([[W * 0.38, H * 0.18], [W * 0.62, H * 0.18], [W * 0.98, H], [W * 0.02, H]], np.int32)
        cv2.fillPoly(img, [road], (95, 95, 95))
        for i in range(8):
            y1 = int(H * 0.18 + i * (H * 0.82 / 8))
            y2 = y1 + int(H * 0.05)
            cv2.line(img, (W // 2, y1), (W // 2, y2), (230, 230, 230), 2)
        cv2.rectangle(img, (int(W * 0.84), int(H * 0.45)), (int(W * 0.88), int(H * 0.9)), (40, 160, 230), -1)  # booth
        noise = np.random.default_rng(1).integers(0, 12, (H, W, 1), dtype=np.uint8)
        return cv2.add(img, np.repeat(noise, 3, axis=2))

    def _draw_vehicle(self, frame: np.ndarray, v: SimVehicle) -> Detection | None:
        p = min(v.progress, 1.0)
        scale = 0.18 + 0.82 * p
        base_w = {VehicleType.CAR: 300, VehicleType.TWO_WHEELER: 120, VehicleType.COMMERCIAL: 380}[v.vtype]
        base_h = {VehicleType.CAR: 240, VehicleType.TWO_WHEELER: 220, VehicleType.COMMERCIAL: 330}[v.vtype]
        bw, bh = int(base_w * scale), int(base_h * scale)
        cx = int(W * (0.5 + (v.lane_x - 0.5) * (0.4 + p)))
        bottom = int(H * 0.2 + (H * 0.95 - H * 0.2) * (v.progress / 1.0))
        x1, y1, x2, y2 = cx - bw // 2, bottom - bh, cx + bw // 2, bottom
        if y2 <= 0 or y1 >= H:
            return None
        # body
        cv2.rectangle(frame, (x1, y1 + bh // 3), (x2, y2), v.color, -1)
        cv2.rectangle(frame, (x1 + bw // 8, y1), (x2 - bw // 8, y1 + bh // 3 + 4), tuple(int(c * 0.8) for c in v.color), -1)
        cv2.rectangle(frame, (x1 + bw // 6, y1 + bh // 14), (x2 - bw // 6, y1 + bh // 3), (60, 50, 40), -1)  # windshield
        if v.vtype != VehicleType.TWO_WHEELER:
            cv2.circle(frame, (x1 + bw // 7, y1 + int(bh * 0.55)), max(3, bw // 14), (200, 230, 255), -1)
            cv2.circle(frame, (x2 - bw // 7, y1 + int(bh * 0.55)), max(3, bw // 14), (200, 230, 255), -1)
        # plate
        pw, ph = int(bw * (0.5 if v.vtype != VehicleType.TWO_WHEELER else 0.85)), max(6, int(bh * 0.13))
        px1, py1 = cx - pw // 2, y2 - int(bh * 0.28)
        px2, py2 = px1 + pw, py1 + ph
        plate_color = (0, 215, 255) if v.vtype == VehicleType.COMMERCIAL else (245, 245, 245)
        cv2.rectangle(frame, (px1, py1), (px2, py2), plate_color, -1)
        cv2.rectangle(frame, (px1, py1), (px2, py2), (20, 20, 20), 1)
        font_scale = ph / 32.0
        if font_scale > 0.18 and not v.unreadable:
            (tw, th), _ = cv2.getTextSize(v.plate, cv2.FONT_HERSHEY_SIMPLEX, font_scale, max(1, int(font_scale * 2)))
            fs = font_scale * min(1.0, (pw - 6) / max(tw, 1))
            (tw, th), _ = cv2.getTextSize(v.plate, cv2.FONT_HERSHEY_SIMPLEX, fs, max(1, int(fs * 2)))
            cv2.putText(frame, v.plate, (cx - tw // 2, py1 + (ph + th) // 2), cv2.FONT_HERSHEY_SIMPLEX, fs, (15, 15, 15),
                        max(1, int(fs * 2)), cv2.LINE_AA)
        elif v.unreadable:
            cv2.rectangle(frame, (px1 + 2, py1 + 2), (px2 - 2, py2 - 2), (90, 80, 70), -1)  # mud / glare

        # what YOLO + OCR "would" return for this frame
        vconf = min(0.99, 0.55 + 0.4 * p + self.rng.uniform(-0.05, 0.05))
        det = Detection(bbox=(max(0, x1), max(0, y1), min(W - 1, x2), min(H - 1, y2)), vehicle_type=v.vtype,
                        confidence=vconf, plate_bbox=(max(0, px1), max(0, py1), min(W - 1, px2), min(H - 1, py2)))
        readable_size = p > 0.35
        if readable_size and not v.unreadable and self.rng.random() < 0.85:
            conf = min(0.99, v.plate_quality * self.rng.uniform(0.82, 1.0))
            text = v.plate if self.rng.random() > 0.15 else noisy_read(v.plate, self.rng)
            det.plate_text, det.plate_confidence = text, conf
        return det
