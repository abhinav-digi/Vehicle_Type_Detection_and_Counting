"""
Holds the single latest annotated JPEG frame per source (upload job or
stream), so a preview endpoint can be polled independently of the
processing thread that's producing frames. Only the most recent frame is
kept per key — this is a live preview, not a frame archive.
"""

from __future__ import annotations

import threading
from typing import Optional


class FrameStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._frames: dict[str, bytes] = {}

    def set(self, key: str, jpeg_bytes: bytes) -> None:
        with self._lock:
            self._frames[key] = jpeg_bytes

    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            return self._frames.get(key)

    def clear(self, key: str) -> None:
        with self._lock:
            self._frames.pop(key, None)
