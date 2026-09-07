from __future__ import annotations

from dataclasses import dataclass

from detection.base import Detection


@dataclass
class TrackedDetection(Detection):
    """A Detection that has been assigned a persistent ID across frames.

    Two TrackedDetections with the same track_id (from the same tracker
    instance) represent the same physical vehicle seen in different frames.
    This is what lets the Counter count vehicles once instead of once per
    frame.
    """

    track_id: int = -1
