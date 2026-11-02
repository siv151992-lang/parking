"""Persist captured vehicle / plate images."""
import uuid
from datetime import datetime, timezone

import cv2
import numpy as np

from ..config import settings


def save_image(img: np.ndarray | None, kind: str) -> str | None:
    """Save a BGR image under media/YYYY/MM/DD and return its relative path."""
    if img is None or getattr(img, "size", 0) == 0:
        return None
    now = datetime.now(timezone.utc)
    rel_dir = f"{now:%Y/%m/%d}"
    out_dir = settings.MEDIA_DIR / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}_{kind}.jpg"
    ok = cv2.imwrite(str(out_dir / name), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return f"{rel_dir}/{name}" if ok else None
