"""
The only place that wires all four stages together. Both the video-upload
endpoint and the live-stream endpoint call this same function — this is
what FR4 ("both input types through one pipeline") actually means in code.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from counting.aggregator import VehicleCounter
from detection.base import Detector
from ingestion.base import Frame, FrameSource
from tracking.tracker import VehicleTracker

logger = logging.getLogger(__name__)


def run_pipeline(
    source: FrameSource,
    detector: Detector,
    counter: VehicleCounter,
    on_frame: Optional[Callable[[Frame, list], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> int:
    """
    Runs frames from `source` through detect -> track -> count.

    A fresh VehicleTracker is created per call, since track IDs are only
    meaningful within one continuous run of a single source.

    Returns the number of frames processed. `should_stop` is polled between
    frames so a long-running stream can be cancelled cleanly.
    """
    tracker = VehicleTracker()
    frames_processed = 0

    with source:
        for frame in source.frames():
            if should_stop is not None and should_stop():
                logger.info("Stop requested for source=%s, ending pipeline", source.source_id)
                break

            detections = detector.detect(frame.image)
            tracked = tracker.update(detections)
            counter.process(tracked, source_id=frame.source_id)

            if on_frame is not None:
                on_frame(frame, tracked)

            frames_processed += 1

    return frames_processed
