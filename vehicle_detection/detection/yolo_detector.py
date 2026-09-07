"""
YOLOv8 implementation of the Detector interface.

Uses a COCO-pretrained model, which already covers the vehicle classes we
need for v1 (FR2: "new vehicle" = a known class seen for the first time —
no open-vocabulary detection required). Swapping to a different model later
means writing a new class that satisfies detection.base.Detector; nothing
else in the pipeline changes.
"""

from __future__ import annotations

from typing import List

from ultralytics import YOLO

from .base import Detection, Detector

# COCO class ids we care about for a vehicle counter. Everything else
# (person, dog, traffic light, ...) is discarded at detection time.
VEHICLE_CLASS_IDS = {
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


class YoloVehicleDetector(Detector):
    def __init__(self, model_path: str = "yolov8n.pt", confidence_threshold: float = 0.4):
        self.model = YOLO(model_path)
        self.confidence_threshold = confidence_threshold

    def detect(self, image) -> List[Detection]:
        results = self.model.predict(
            image,
            conf=self.confidence_threshold,
            classes=list(VEHICLE_CLASS_IDS.keys()),
            verbose=False,
        )[0]

        detections: List[Detection] = []
        for box in results.boxes:
            class_id = int(box.cls[0])
            class_name = VEHICLE_CLASS_IDS.get(class_id)
            if class_name is None:
                continue  # shouldn't happen given `classes=` filter, but stay safe
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
            detections.append(
                Detection(
                    class_name=class_name,
                    confidence=float(box.conf[0]),
                    box_xyxy=(x1, y1, x2, y2),
                )
            )
        return detections
