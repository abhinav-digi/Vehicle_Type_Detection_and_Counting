"""
Assigns persistent IDs to detections across frames using ByteTrack (via the
`supervision` library). One VehicleTracker instance should be used for the
lifetime of a single video/stream run — track IDs are only meaningful within
that run, they are not stable across separate uploads or a stream restart.
"""

from __future__ import annotations

from typing import List

import numpy as np
import supervision as sv

from detection.base import Detection
from .base import TrackedDetection


class VehicleTracker:
    def __init__(self):
        # NOTE: sv.ByteTrack is flagged deprecated upstream (in favor of a
        # future replacement not yet released as of supervision 0.30.0) but
        # remains fully functional. Revisit if upgrading past supervision 0.30.x.
        self._tracker = sv.ByteTrack()
        self._class_name_to_id: dict[str, int] = {}
        self._id_to_class_name: dict[int, str] = {}

    def _class_id_for(self, name: str) -> int:
        if name not in self._class_name_to_id:
            new_id = len(self._class_name_to_id)
            self._class_name_to_id[name] = new_id
            self._id_to_class_name[new_id] = name
        return self._class_name_to_id[name]

    def update(self, detections: List[Detection]) -> List[TrackedDetection]:
        if detections:
            xyxy = np.array([d.box_xyxy for d in detections], dtype=np.float32)
            confidence = np.array([d.confidence for d in detections], dtype=np.float32)
            class_id = np.array(
                [self._class_id_for(d.class_name) for d in detections], dtype=int
            )
        else:
            xyxy = np.empty((0, 4), dtype=np.float32)
            confidence = np.empty((0,), dtype=np.float32)
            class_id = np.empty((0,), dtype=int)

        sv_detections = sv.Detections(
            xyxy=xyxy, confidence=confidence, class_id=class_id
        )
        tracked = self._tracker.update_with_detections(sv_detections)

        results: List[TrackedDetection] = []
        for i in range(len(tracked)):
            class_name = self._id_to_class_name[int(tracked.class_id[i])]
            results.append(
                TrackedDetection(
                    class_name=class_name,
                    confidence=float(tracked.confidence[i]),
                    box_xyxy=tuple(float(v) for v in tracked.xyxy[i]),
                    track_id=int(tracked.tracker_id[i]),
                )
            )
        return results
