"""
Common interface for detection models. Keeping this contract narrow is what
lets us swap YOLOv8 for a different model later without touching the
tracker/counter code (FR5 — modularity).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Detection:
    """One detected object in one frame."""

    class_name: str  # e.g. "car", "truck", "bus"
    confidence: float
    box_xyxy: Tuple[float, float, float, float]  # (x1, y1, x2, y2) in pixels


class Detector:
    """Base class every detection backend implements."""

    def detect(self, image) -> List[Detection]:
        """Run detection on a single BGR image, return vehicle detections only."""
        raise NotImplementedError
