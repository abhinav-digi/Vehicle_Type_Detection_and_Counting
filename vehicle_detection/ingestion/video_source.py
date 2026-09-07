"""
Single ingestion class for both FR4 input types:
  - an uploaded video file  ->  path like "/data/uploads/clip.mp4"
  - a live camera stream    ->  a static URL like "rtsp://camera-ip/stream"
                                 or "http://camera-ip/video"

cv2.VideoCapture accepts either transparently, so one class covers both.
The only real difference at runtime is that a file has a natural end
(frames() just stops), while a stream keeps yielding until closed or the
connection drops.
"""

from __future__ import annotations

import logging
import time
from typing import Iterator, Optional

import cv2

from .base import Frame, FrameSource

logger = logging.getLogger(__name__)


class VideoSource(FrameSource):
    """
    Args:
        source_id: a name to tag frames/events with (e.g. "upload-<uuid>"
            or "camera-north-gate").
        location: file path OR stream URL — passed straight to cv2.VideoCapture.
        is_stream: if True, treat as a live source: on a dropped connection,
            attempt to reconnect instead of stopping. If False (uploaded
            file), reaching the end simply ends iteration.
        reconnect_delay_s: how long to wait between reconnect attempts for
            live streams.
    """

    def __init__(
        self,
        source_id: str,
        location: str,
        is_stream: bool = False,
        reconnect_delay_s: float = 2.0,
    ):
        super().__init__(source_id)
        self.location = location
        self.is_stream = is_stream
        self.reconnect_delay_s = reconnect_delay_s
        self._cap: Optional[cv2.VideoCapture] = None
        self._stopped = False

    def _open(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.location)
        if not cap.isOpened():
            raise ConnectionError(
                f"Could not open video source '{self.location}' "
                f"(source_id={self.source_id})"
            )
        return cap

    def frames(self) -> Iterator[Frame]:
        self._cap = self._open()
        index = 0
        try:
            while not self._stopped:
                ok, image = self._cap.read()
                if not ok:
                    if self.is_stream:
                        logger.warning(
                            "Stream %s dropped, reconnecting in %.1fs",
                            self.source_id,
                            self.reconnect_delay_s,
                        )
                        self._cap.release()
                        time.sleep(self.reconnect_delay_s)
                        self._cap = self._open()
                        continue
                    else:
                        # Uploaded file: no more frames, we're done.
                        break

                timestamp_ms = self._cap.get(cv2.CAP_PROP_POS_MSEC)
                yield Frame(
                    index=index,
                    image=image,
                    timestamp_ms=timestamp_ms,
                    source_id=self.source_id,
                )
                index += 1
        finally:
            self.close()

    def stop(self) -> None:
        """Signal a running stream to stop on its next loop iteration."""
        self._stopped = True

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
