"""
Common interface every ingestion source (uploaded file, live stream) implements.
Keeping this contract tiny is what lets the rest of the pipeline (detector,
tracker, counter) stay ignorant of *where* frames came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional

import numpy as np


@dataclass
class Frame:
    """A single decoded video frame plus metadata needed downstream."""

    index: int  # sequential frame number since this source was opened
    image: np.ndarray  # BGR image array (OpenCV convention)
    timestamp_ms: float  # position in the source, in milliseconds
    source_id: str  # identifies which upload/stream this frame came from


class FrameSource:
    """
    Base class for anything that can yield a sequence of Frames.

    Subclasses only need to implement `frames()`. Both an uploaded video file
    and a live RTSP/HTTP camera stream satisfy this same interface, so the
    detector/tracker/counter code never needs to know which one it's looking at.
    """

    def __init__(self, source_id: str):
        self.source_id = source_id

    def frames(self) -> Iterator[Frame]:
        raise NotImplementedError

    def close(self) -> None:
        """Release any underlying resources (file handles, network sockets)."""
        pass

    def __enter__(self) -> "FrameSource":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
