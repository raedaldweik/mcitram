"""In-memory store for rendered report images.

Visual Analytics report renderings (SVG/PNG) are cached here by the VA tools
and served to the browser via GET /api/va/image/{image_id} — so the chat can
display live dashboard snapshots without ever pushing image bytes through the
LLM context or the trace.
"""
from __future__ import annotations

import threading
import time
import uuid

_MAX_ITEMS = 200
_TTL_SECONDS = 6 * 3600

_lock = threading.Lock()
_images: dict[str, tuple[bytes, str, float]] = {}   # id -> (bytes, content_type, ts)


def put(data: bytes, content_type: str) -> str:
    image_id = uuid.uuid4().hex[:16]
    now = time.time()
    with _lock:
        # evict expired, then oldest if still over budget
        expired = [k for k, (_, _, ts) in _images.items() if now - ts > _TTL_SECONDS]
        for k in expired:
            del _images[k]
        while len(_images) >= _MAX_ITEMS:
            oldest = min(_images, key=lambda k: _images[k][2])
            del _images[oldest]
        _images[image_id] = (data, content_type, now)
    return image_id


def get(image_id: str) -> tuple[bytes, str] | None:
    with _lock:
        item = _images.get(image_id)
    if not item:
        return None
    return item[0], item[1]
