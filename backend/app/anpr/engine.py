"""Real ANPR engine: YOLO vehicle detection + plate localisation + PaddleOCR.

Pipeline per processed frame:
  1. YOLO (COCO) detects car / motorcycle / bus / truck.
  2. For each vehicle in the lower part of the frame, locate the plate:
       a. dedicated plate YOLO model if YOLO_PLATE_MODEL is configured, else
       b. OpenCV morphology (black-hat + Sobel + aspect-ratio filter), else
       c. PaddleOCR text detection on the lower half of the vehicle crop.
  3. PaddleOCR recognises the plate (two-row plates are merged top-to-bottom).
  4. Text is normalised and returned as tracker Detections; voting across
     frames happens in the tracker.

Models are loaded once and shared by all camera workers; inference is
serialised with a lock (PaddleOCR / Torch models are not thread-safe).
"""
from __future__ import annotations

import logging
import re
import threading

import cv2
import numpy as np

from ..config import settings
from ..models import VehicleType
from .tracker import Detection

log = logging.getLogger("anpr.engine")

COCO_TO_TYPE = {2: VehicleType.CAR, 3: VehicleType.TWO_WHEELER, 5: VehicleType.COMMERCIAL, 7: VehicleType.COMMERCIAL}
PLATE_RE = re.compile(r"[^A-Z0-9]")


class ANPREngine:
    _instance: "ANPREngine | None" = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self.vehicle_model = None
        self.plate_model = None
        self.ocr = None
        self.error: str | None = None
        self.loaded = False
        self._infer_lock = threading.Lock()

    @classmethod
    def get(cls) -> "ANPREngine":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = ANPREngine()
                cls._instance._load()
            return cls._instance

    @classmethod
    def status(cls) -> dict:
        inst = cls._instance
        if inst is None:
            return {"loaded": False, "error": None, "initialised": False}
        return {
            "initialised": True,
            "loaded": inst.loaded,
            "error": inst.error,
            "vehicle_model": settings.YOLO_VEHICLE_MODEL if inst.vehicle_model else None,
            "plate_model": settings.YOLO_PLATE_MODEL if inst.plate_model else "opencv-morphology",
            "ocr": "PaddleOCR" if inst.ocr else None,
        }

    @property
    def available(self) -> bool:
        return self.loaded

    def _load(self):
        try:
            from ultralytics import YOLO  # noqa: WPS433
        except Exception as e:  # pragma: no cover - depends on optional deps
            self.error = f"ultralytics not installed ({e}). Install requirements-ai.txt"
            log.warning(self.error)
            return
        try:
            from paddleocr import PaddleOCR  # noqa: WPS433
        except Exception as e:  # pragma: no cover
            self.error = f"paddleocr not installed ({e}). Install requirements-ai.txt"
            log.warning(self.error)
            return
        try:
            self.vehicle_model = YOLO(settings.YOLO_VEHICLE_MODEL)
            if settings.YOLO_PLATE_MODEL:
                self.plate_model = YOLO(settings.YOLO_PLATE_MODEL)
            self.ocr = PaddleOCR(use_angle_cls=True, lang=settings.OCR_LANG, use_gpu=settings.OCR_USE_GPU, show_log=False)
            self.loaded = True
            log.info("ANPR engine loaded (YOLO=%s, plate=%s)", settings.YOLO_VEHICLE_MODEL, settings.YOLO_PLATE_MODEL or "opencv")
        except Exception as e:  # pragma: no cover
            self.error = f"Failed to load ANPR models: {e}"
            log.exception(self.error)

    # ------------------------------------------------------------ inference
    def detect(self, frame: np.ndarray, zone_top: float = 0.0) -> list[Detection]:
        if not self.loaded:
            return []
        with self._infer_lock:
            return self._detect(frame, zone_top)

    def _detect(self, frame: np.ndarray, zone_top: float) -> list[Detection]:
        h, w = frame.shape[:2]
        res = self.vehicle_model.predict(
            frame, conf=settings.VEHICLE_CONF_THRESHOLD, classes=list(COCO_TO_TYPE), device=settings.YOLO_DEVICE, verbose=False
        )[0]
        out: list[Detection] = []
        boxes = res.boxes
        for i in range(len(boxes)):
            x1, y1, x2, y2 = boxes.xyxy[i].tolist()
            cls = int(boxes.cls[i])
            conf = float(boxes.conf[i])
            det = Detection(bbox=(x1, y1, x2, y2), vehicle_type=COCO_TO_TYPE.get(cls, VehicleType.CAR), confidence=conf)
            # Only spend OCR time on vehicles that reached the detection zone.
            if y2 >= zone_top * h and (x2 - x1) * (y2 - y1) > 0.004 * w * h:
                text, pconf, pbox = self.read_plate(frame, (int(x1), int(y1), int(x2), int(y2)))
                det.plate_text, det.plate_confidence, det.plate_bbox = text, pconf, pbox
            out.append(det)
        return out

    def read_plate(self, frame: np.ndarray, vbox) -> tuple[str | None, float, tuple | None]:
        x1, y1, x2, y2 = vbox
        crop = frame[max(0, y1):y2, max(0, x1):x2]
        if crop.size == 0:
            return None, 0.0, None
        candidates: list[tuple[int, int, int, int]] = []
        if self.plate_model is not None:
            r = self.plate_model.predict(crop, conf=0.25, device=settings.YOLO_DEVICE, verbose=False)[0]
            for b in r.boxes.xyxy.tolist():
                candidates.append(tuple(int(v) for v in b))
        if not candidates:
            candidates = localize_plates_opencv(crop)
        best = (None, 0.0, None)
        for (px1, py1, px2, py2) in candidates[:3]:
            plate_img = crop[py1:py2, px1:px2]
            text, conf = self._ocr_plate(plate_img, det=False)
            if text and conf > best[1]:
                best = (text, conf, (x1 + px1, y1 + py1, x1 + px2, y1 + py2))
        if best[0] is None:
            # Fallback: let PaddleOCR's own text detector search the lower half.
            ch = crop.shape[0]
            lower = crop[ch // 3:, :]
            text, conf = self._ocr_plate(lower, det=True)
            if text:
                best = (text, conf * 0.9, (x1, y1 + ch // 3, x2, y2))
        return best

    def _ocr_plate(self, img: np.ndarray, det: bool) -> tuple[str | None, float]:
        if img is None or img.size == 0 or min(img.shape[:2]) < 8:
            return None, 0.0
        img = preprocess_plate(img)
        try:
            result = self.ocr.ocr(img, det=det, cls=True)
        except Exception:  # pragma: no cover
            log.exception("OCR failed")
            return None, 0.0
        lines: list[tuple[float, float, str, float]] = []  # (y, x, text, conf)
        for page in result or []:
            for item in page or []:
                if det:
                    box, (txt, conf) = item
                    ys = [p[1] for p in box]
                    xs = [p[0] for p in box]
                    lines.append((sum(ys) / 4, min(xs), txt, float(conf)))
                else:
                    txt, conf = item
                    lines.append((0, 0, txt, float(conf)))
        if not lines:
            return None, 0.0
        # merge two-row plates: sort by row then column
        lines.sort(key=lambda t: (round(t[0] / 12), t[1]))
        texts = [(PLATE_RE.sub("", t.upper()), c) for _, _, t, c in lines]
        texts = [(t, c) for t, c in texts if t]
        if not texts:
            return None, 0.0
        merged = "".join(t for t, _ in texts)
        conf = min(c for _, c in texts)
        if not (4 <= len(merged) <= 12):
            # pick the single longest plausible token instead
            plausible = [(t, c) for t, c in texts if 4 <= len(t) <= 12]
            if not plausible:
                return None, 0.0
            merged, conf = max(plausible, key=lambda tc: (len(tc[0]), tc[1]))
        return merged, conf


def preprocess_plate(img: np.ndarray) -> np.ndarray:
    """Upscale small plates and boost contrast (CLAHE) for OCR."""
    h, w = img.shape[:2]
    if h < 48:
        scale = 48 / h
        img = cv2.resize(img, (int(w * scale), 48), interpolation=cv2.INTER_CUBIC)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def localize_plates_opencv(vehicle: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Classical plate localisation; returns candidate boxes sorted by score."""
    h, w = vehicle.shape[:2]
    if h < 20 or w < 20:
        return []
    gray = cv2.cvtColor(vehicle, cv2.COLOR_BGR2GRAY)
    rect_kern = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, rect_kern)
    light = cv2.threshold(cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))), 0, 255,
                          cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    grad = cv2.Sobel(blackhat, cv2.CV_32F, 1, 0, ksize=-1)
    grad = np.absolute(grad)
    mn, mx = grad.min(), grad.max()
    grad = ((grad - mn) / (mx - mn + 1e-6) * 255).astype("uint8")
    grad = cv2.GaussianBlur(grad, (5, 5), 0)
    grad = cv2.morphologyEx(grad, cv2.MORPH_CLOSE, rect_kern)
    thresh = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    thresh = cv2.erode(thresh, None, iterations=2)
    thresh = cv2.dilate(thresh, None, iterations=2)
    thresh = cv2.bitwise_and(thresh, thresh, mask=light)
    thresh = cv2.dilate(thresh, None, iterations=2)
    cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        ar = cw / float(ch + 1e-6)
        area_ratio = (cw * ch) / float(w * h)
        if 1.5 <= ar <= 6.5 and 0.005 <= area_ratio <= 0.25 and y > h * 0.25:
            score = area_ratio * (1.0 if 2.5 <= ar <= 5.5 else 0.5) * (y / h)
            out.append((score, (x, y, x + cw, y + ch)))
    out.sort(reverse=True)
    return [b for _, b in out]


if __name__ == "__main__":  # python -m app.anpr.engine --preload  (used by the Docker build)
    import sys

    logging.basicConfig(level=logging.INFO)
    eng = ANPREngine.get()
    if not eng.available:
        sys.exit(f"ANPR engine failed to load: {eng.error}")
    eng.detect(np.zeros((480, 640, 3), np.uint8))
    eng._ocr_plate(np.full((60, 240, 3), 255, np.uint8), det=False)
    print("ANPR engine ready:", ANPREngine.status())
