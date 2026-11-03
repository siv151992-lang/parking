"""Frame sources: real RTSP/HTTP/file streams via OpenCV."""
from __future__ import annotations

import os
import threading
import time
from urllib.parse import quote, urlparse, urlunparse

import cv2
import numpy as np

# Prefer TCP for RTSP: far fewer corrupted frames than UDP on busy networks.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")


class SourceError(Exception):
    pass


def build_stream_url(rtsp_url: str, username: str = "", password: str = "") -> str:
    """Inject credentials into an RTSP URL if they are not already present."""
    if not username or not rtsp_url.lower().startswith(("rtsp://", "http://", "https://")):
        return rtsp_url
    p = urlparse(rtsp_url)
    if p.username:
        return rtsp_url
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{p.hostname}"
    if p.port:
        netloc += f":{p.port}"
    return urlunparse(p._replace(netloc=netloc))


def redact_url(url: str) -> str:
    p = urlparse(url)
    if p.password:
        return url.replace(f":{p.password}@", ":****@")
    return url


class OpenCVSource:
    """Reads an RTSP/HTTP stream or a video file.

    A background grabber thread always keeps only the newest frame so slow
    ANPR processing never causes the stream to lag behind real time.
    Video files are looped and played at their native FPS (useful for tests
    with recorded footage)."""

    is_simulated = False

    def __init__(self, url: str, read_timeout: float = 10.0):
        self.url = url
        self.read_timeout = read_timeout
        self.cap: cv2.VideoCapture | None = None
        self._frame: np.ndarray | None = None
        self._frame_time = 0.0
        self._seq = 0
        self._last_read_seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.is_file = os.path.isfile(url)
        self.fps = 0.0

    def open(self):
        self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        if not self.cap.isOpened():
            self.cap.release()
            if self.is_file:
                raise SourceError(f"Unable to open video file {self.url}")
            from .rtsp_probe import diagnose
            reason = diagnose(self.url) if self.url.lower().startswith("rtsp://") else None
            raise SourceError(reason or (
                f"The camera accepted the login, but the video of {redact_url(self.url)} could not be decoded. "
                "Set the camera's video encoding to H.264, or try the sub-stream (e.g. channel 102)."
                if self.url.lower().startswith("rtsp://") else f"Unable to open stream {redact_url(self.url)}"))
        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.cap.release()
            raise SourceError("Stream opened but returned no frames")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        with self._lock:
            self._frame, self._frame_time, self._seq = frame, time.monotonic(), 1
        self._thread = threading.Thread(target=self._grab_loop, daemon=True, name=f"grab-{redact_url(self.url)[:30]}")
        self._thread.start()

    def _grab_loop(self):
        delay = 1.0 / self.fps if self.is_file and self.fps > 0 else 0
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            if not ok or frame is None:
                if self.is_file:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                time.sleep(0.05)
                continue
            with self._lock:
                self._frame, self._frame_time = frame, time.monotonic()
                self._seq += 1
            if delay:
                time.sleep(delay)

    def read(self) -> np.ndarray:
        deadline = time.monotonic() + self.read_timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._seq != self._last_read_seq and self._frame is not None:
                    self._last_read_seq = self._seq
                    return self._frame
                stale = time.monotonic() - self._frame_time
            if stale > self.read_timeout:
                break
            time.sleep(0.01)
        raise SourceError(f"No frames received for {self.read_timeout:.0f}s")

    def detections(self):
        return None  # real sources use the ANPR engine

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self.cap is not None:
            self.cap.release()
