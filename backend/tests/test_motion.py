"""Motion gate: YOLO is skipped while nothing moves in the detection zone."""
import cv2
import numpy as np

from app.anpr.tracker import DEFAULT_ZONE
from app.anpr.worker import CameraWorker


def frame(x=None):
    f = np.full((720, 1280, 3), 90, np.uint8)
    if x is not None:
        cv2.rectangle(f, (x, 350), (x + 220, 520), (0, 0, 200), -1)
    return f


def test_motion_gate():
    w = CameraWorker(1)
    assert w._motion(frame(), DEFAULT_ZONE) is True             # first frame: no reference yet
    assert w._motion(frame(), DEFAULT_ZONE) is False            # nothing changed
    noisy = frame() + np.random.default_rng(1).integers(0, 4, (720, 1280, 3), dtype=np.uint8)
    assert w._motion(noisy, DEFAULT_ZONE) is False              # sensor noise is not motion
    assert w._motion(frame(300), DEFAULT_ZONE) is True          # a vehicle appears
    assert w._motion(frame(340), DEFAULT_ZONE) is True          # and moves
    assert w._motion(frame(340), DEFAULT_ZONE) is False         # it stopped
