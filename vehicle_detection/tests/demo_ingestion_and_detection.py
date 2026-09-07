"""
Step 1 validation: ingestion + detection working together, on a real video
file. Prints per-frame vehicle counts (raw detections — no tracking/dedup
yet, that's the next step).

Usage:
    python3 tests/demo_ingestion_and_detection.py <path-or-stream-url> [--stream]
"""

import argparse
import sys
from collections import Counter

sys.path.insert(0, ".")

from detection.yolo_detector import YoloVehicleDetector
from ingestion.video_source import VideoSource


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("location", help="Video file path or stream URL")
    parser.add_argument(
        "--stream", action="store_true", help="Treat location as a live stream"
    )
    parser.add_argument("--max-frames", type=int, default=None)
    args = parser.parse_args()

    detector = YoloVehicleDetector()
    source = VideoSource(
        source_id="demo-source", location=args.location, is_stream=args.stream
    )

    total_detections = Counter()
    frame_count = 0

    with source:
        for frame in source.frames():
            detections = detector.detect(frame.image)
            frame_count += 1
            for d in detections:
                total_detections[d.class_name] += 1

            if detections:
                summary = ", ".join(f"{d.class_name}({d.confidence:.2f})" for d in detections)
                print(f"frame {frame.index:>4}  t={frame.timestamp_ms:>8.0f}ms  -> {summary}")

            if args.max_frames and frame_count >= args.max_frames:
                break

    print("\n--- Summary (raw per-frame detections, not unique vehicles) ---")
    print(f"Frames processed: {frame_count}")
    for class_name, count in total_detections.items():
        print(f"  {class_name}: {count} detections across all frames")


if __name__ == "__main__":
    main()
