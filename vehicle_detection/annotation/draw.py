"""
Turns a frame + tracked detections into an annotated frame for the live
preview 
(FR: "play video on the UI and mark the objects during processing").
"""

from __future__ import annotations

from typing import List

import cv2
import numpy as np

from tracking.base import TrackedDetection

# Distinct, high-contrast colors per class (BGR, since OpenCV) so vehicle
# types are visually distinguishable at a glance over arbitrary footage.
CLASS_COLORS = {
    "car": (60, 180, 250),
    "truck": (50, 130, 246),
    "bus": (80, 90, 236),
    "motorcycle": (215, 155, 70),
    "bicycle": (120, 200, 80),
}
DEFAULT_COLOR = (200, 200, 200)
FONT = cv2.FONT_HERSHEY_SIMPLEX


def draw_detections(image: np.ndarray, detections: List[TrackedDetection]) -> np.ndarray:
    """Returns a NEW annotated copy of `image`; the original is untouched."""
    annotated = image.copy()

    for d in detections:
        x1, y1, x2, y2 = (int(v) for v in d.box_xyxy)
        color = CLASS_COLORS.get(d.class_name, DEFAULT_COLOR)

        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

        label = f"{d.class_name} #{d.track_id}"
        (text_w, text_h), baseline = cv2.getTextSize(label, FONT, 0.5, 1)
        label_top = max(y1 - text_h - baseline - 4, 0)
        cv2.rectangle(annotated, (x1, label_top), (x1 + text_w + 6, y1), color, -1)
        cv2.putText(
            annotated,
            label,
            (x1 + 3, y1 - 4),
            FONT,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    return annotated


def encode_jpeg(image: np.ndarray, quality: int = 80) -> bytes | None:
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buffer.tobytes() if ok else None
