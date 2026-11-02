"""Multi-object vehicle tracker with detection-zone triggering and plate voting.

Each physical vehicle becomes one Track. A track produces exactly ONE
TrackEvent during its lifetime, so a vehicle waiting in front of the camera
(e.g. at a barrier) is never counted twice.

A track triggers when its anchor point (bottom-centre of the box)
  * crosses the trigger line inside the detection zone, or
  * stays inside the zone for `presence_frames` frames with enough
    consistent plate reads (stop-and-go barrier lanes).
After triggering, the event is finalised once enough OCR reads agree, after
`max_wait_frames`, or when the track disappears - whichever comes first.
"""
from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

DEFAULT_ZONE = {"polygon": [[0.05, 0.25], [0.95, 0.25], [0.95, 0.98], [0.05, 0.98]], "trigger_line": 0.62}


@dataclass
class Detection:
    """One vehicle seen in one frame (from YOLO or the simulator)."""
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels
    vehicle_type: str
    confidence: float
    plate_text: str | None = None
    plate_confidence: float = 0.0
    plate_bbox: tuple[int, int, int, int] | None = None  # absolute pixels


@dataclass
class TrackEvent:
    track_id: str
    vehicle_type: str
    vehicle_confidence: float
    plate_text: str | None
    plate_confidence: float
    ocr_reads: int
    bbox: list
    vehicle_crop: np.ndarray | None
    plate_crop: np.ndarray | None
    trigger: str  # "line" | "presence" | "lost"


@dataclass
class Track:
    id: str
    bbox: tuple
    first_anchor: tuple
    anchor: tuple
    hits: int = 1
    missed: int = 0
    frames_in_zone: int = 0
    type_votes: Counter = field(default_factory=Counter)
    vehicle_conf_max: float = 0.0
    plate_reads: list = field(default_factory=list)  # (text, conf)
    best_plate_conf: float = -1.0
    best_vehicle_area: float = 0.0
    vehicle_crop: np.ndarray | None = None
    plate_crop: np.ndarray | None = None
    triggered: bool = False
    trigger_reason: str = ""
    trigger_frame: int = 0
    emitted: bool = False
    prev_side: int | None = None


def iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-9)


def point_in_polygon(x: float, y: float, poly: list) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def vote_plate(reads: list[tuple[str, float]]) -> tuple[str | None, float]:
    """Confidence-weighted vote across OCR reads of the same vehicle.

    Whole-string voting first; if no string clearly wins, fall back to
    per-character voting among reads of the modal length."""
    reads = [(t, c) for t, c in reads if t]
    if not reads:
        return None, 0.0
    scores: dict[str, float] = defaultdict(float)
    for t, c in reads:
        scores[t] += c
    total = sum(scores.values())
    best, best_score = max(scores.items(), key=lambda kv: kv[1])
    agreement = best_score / total
    best_confs = [c for t, c in reads if t == best]
    if agreement < 0.5 and len(reads) >= 3:
        modal_len = Counter(len(t) for t, _ in reads).most_common(1)[0][0]
        same_len = [(t, c) for t, c in reads if len(t) == modal_len]
        chars = []
        char_conf = []
        for i in range(modal_len):
            cs: dict[str, float] = defaultdict(float)
            for t, c in same_len:
                cs[t[i]] += c
            ch, sc = max(cs.items(), key=lambda kv: kv[1])
            chars.append(ch)
            char_conf.append(sc / sum(cs.values()))
        best = "".join(chars)
        avg = sum(c for _, c in same_len) / len(same_len)
        return best, float(avg * min(char_conf))
    avg_best = sum(best_confs) / len(best_confs)
    return best, float(avg_best * (0.5 + 0.5 * agreement))


class VehicleTracker:
    def __init__(self, zone: dict | None = None, iou_threshold: float = 0.25, max_missed: int = 12,
                 presence_frames: int = 25, min_votes: int = 3, max_wait_frames: int = 15):
        self.zone = zone or DEFAULT_ZONE
        self.iou_threshold = iou_threshold
        self.max_missed = max_missed
        self.presence_frames = presence_frames
        self.min_votes = min_votes
        self.max_wait_frames = max_wait_frames
        self.tracks: dict[str, Track] = {}
        self.frame_idx = 0
        self._ids = itertools.count(1)
        self.prefix = ""

    def set_zone(self, zone: dict | None):
        self.zone = zone or DEFAULT_ZONE

    # --------------------------------------------------------------- update
    def update(self, detections: list[Detection], frame: np.ndarray | None) -> list[TrackEvent]:
        self.frame_idx += 1
        h, w = (frame.shape[:2] if frame is not None else (1, 1))
        poly = [(px * w, py * h) for px, py in self.zone.get("polygon", DEFAULT_ZONE["polygon"])]
        line_y = float(self.zone.get("trigger_line", DEFAULT_ZONE["trigger_line"])) * h

        # Greedy IoU matching (adequate for gate lanes with few vehicles at once)
        unmatched = set(range(len(detections)))
        pairs = []
        for tid, tr in self.tracks.items():
            for di in unmatched:
                score = iou(tr.bbox, detections[di].bbox)
                if score >= self.iou_threshold:
                    pairs.append((score, tid, di))
        pairs.sort(reverse=True)
        used_t, used_d = set(), set()
        for _, tid, di in pairs:
            if tid in used_t or di in used_d:
                continue
            used_t.add(tid)
            used_d.add(di)
            self._update_track(self.tracks[tid], detections[di], frame)
        for tid, tr in self.tracks.items():
            if tid not in used_t:
                tr.missed += 1
        for di in unmatched - used_d:
            d = detections[di]
            anchor = ((d.bbox[0] + d.bbox[2]) / 2, d.bbox[3])
            tr = Track(id=f"{self.prefix}{next(self._ids)}", bbox=d.bbox, first_anchor=anchor, anchor=anchor)
            self.tracks[tr.id] = tr
            self._update_track(tr, d, frame, new=True)

        events: list[TrackEvent] = []
        for tid, tr in list(self.tracks.items()):
            if tr.missed == 0:
                ax, ay = tr.anchor
                in_zone = point_in_polygon(ax, ay, poly)
                side = 1 if ay >= line_y else -1
                if in_zone:
                    tr.frames_in_zone += 1
                    if not tr.triggered and tr.prev_side is not None and side != tr.prev_side:
                        self._trigger(tr, "line")
                    if not tr.triggered and tr.frames_in_zone >= self.presence_frames and self._votes(tr) >= self.min_votes:
                        self._trigger(tr, "presence")
                tr.prev_side = side
            # finalise
            if tr.triggered and not tr.emitted:
                waited = self.frame_idx - tr.trigger_frame
                if self._votes(tr) >= self.min_votes or waited >= self.max_wait_frames or tr.missed > 0:
                    events.append(self._emit(tr, tr.trigger_reason))
            if tr.missed > self.max_missed:
                # A vehicle that was inside the zone long enough but never crossed the
                # line (e.g. it reversed out) is NOT counted.
                del self.tracks[tid]
        return events

    def _votes(self, tr: Track) -> int:
        if not tr.plate_reads:
            return 0
        return Counter(t for t, _ in tr.plate_reads).most_common(1)[0][1]

    def _trigger(self, tr: Track, reason: str):
        tr.triggered = True
        tr.trigger_reason = reason
        tr.trigger_frame = self.frame_idx

    def _update_track(self, tr: Track, d: Detection, frame, new=False):
        if not new:
            tr.hits += 1
        tr.missed = 0
        tr.bbox = d.bbox
        tr.anchor = ((d.bbox[0] + d.bbox[2]) / 2, d.bbox[3])
        tr.type_votes[d.vehicle_type] += d.confidence
        tr.vehicle_conf_max = max(tr.vehicle_conf_max, d.confidence)
        area = (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1])
        if frame is not None and area > tr.best_vehicle_area:
            tr.best_vehicle_area = area
            tr.vehicle_crop = _crop(frame, d.bbox, pad=0.05)
        if d.plate_text:
            tr.plate_reads.append((d.plate_text, d.plate_confidence))
            if frame is not None and d.plate_bbox and d.plate_confidence > tr.best_plate_conf:
                tr.best_plate_conf = d.plate_confidence
                tr.plate_crop = _crop(frame, d.plate_bbox, pad=0.08)
        elif frame is not None and d.plate_bbox and tr.plate_crop is None:
            tr.plate_crop = _crop(frame, d.plate_bbox, pad=0.08)

    def _emit(self, tr: Track, reason: str) -> TrackEvent:
        tr.emitted = True
        text, conf = vote_plate(tr.plate_reads)
        vtype = tr.type_votes.most_common(1)[0][0] if tr.type_votes else "CAR"
        return TrackEvent(
            track_id=tr.id, vehicle_type=vtype, vehicle_confidence=tr.vehicle_conf_max, plate_text=text,
            plate_confidence=conf, ocr_reads=len(tr.plate_reads), bbox=[float(v) for v in tr.bbox],
            vehicle_crop=tr.vehicle_crop, plate_crop=tr.plate_crop, trigger=reason,
        )

    def active_tracks(self) -> list[Track]:
        return [t for t in self.tracks.values() if t.missed == 0]


def _crop(frame: np.ndarray, bbox, pad: float = 0.0) -> np.ndarray | None:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    pw, ph = (x2 - x1) * pad, (y2 - y1) * pad
    x1, y1 = int(max(0, x1 - pw)), int(max(0, y1 - ph))
    x2, y2 = int(min(w, x2 + pw)), int(min(h, y2 + ph))
    if x2 <= x1 or y2 <= y1:
        return None
    return frame[y1:y2, x1:x2].copy()
