"""
API layer. Wires everything built so far behind HTTP endpoints:

  POST   /api/videos/upload           - process an uploaded video file
  GET    /api/videos/{job_id}/status  - poll upload processing progress
  GET    /api/videos/{job_id}/preview - live annotated MJPEG preview (boxes drawn as it processes)
  POST   /api/streams                 - start processing a live camera URL
  GET    /api/streams                 - list active/stopped streams
  DELETE /api/streams/{stream_id}     - stop a running stream
  GET    /api/streams/{stream_id}/preview - live annotated MJPEG preview
  GET    /api/counts/live             - today's counts by vehicle type
  GET    /api/counts/history          - historical counts (?date=YYYY-MM-DD)
  GET    /api/vehicle-types           - registry of known vehicle types

The preview endpoints are plain MJPEG (multipart/x-mixed-replace) streams,
which any <img> tag can display directly with no client-side video/canvas
code. Each processing frame gets bounding boxes drawn on it (annotation/)
and published to a small in-memory FrameStore keyed by job_id/stream_id;
the preview endpoint just polls that store and streams whatever's latest.

Video/stream processing is CPU-bound and blocking (OpenCV + YOLO), so each
upload/stream runs in its own background thread rather than as an async
task, and progress is reported back through simple in-memory dicts. Currently using
single-camera for POC scale ; a job queue (e.g. Celery/RQ) would be the natural
upgrade for higher concurrency.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import date as date_type
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from annotation.draw import draw_detections, encode_jpeg
from api.frame_store import FrameStore
from counting.aggregator import VehicleCounter
from detection.yolo_detector import YoloVehicleDetector
from ingestion.video_source import VideoSource
from pipeline.runner import run_pipeline
from scheduler.daily_job import start_scheduler
from storage.db import SessionLocal, init_db
from storage.models import DailyVehicleCount, VehicleType

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UI_DIR = Path(__file__).parent.parent / "ui"
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Vehicle Detection & Counting API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared, process-wide instances. The detector is expensive to load, so one
# instance is reused across all requests/threads (YOLO inference itself is
# safe to call from multiple threads). The counter's in-memory "already
# counted" set is intentionally shared across all sources it processes.
detector = YoloVehicleDetector()
counter = VehicleCounter(session_factory=SessionLocal)
frame_store = FrameStore()

# job_id / stream_id -> status dict. In-memory only (see module docstring).
upload_jobs: dict[str, dict] = {}
active_streams: dict[str, dict] = {}
_stream_sources: dict[str, VideoSource] = {}


@app.on_event("startup")
def on_startup():
    init_db()
    start_scheduler(SessionLocal)


class StreamCreateRequest(BaseModel):
    name: str
    url: str


def _mjpeg_stream(key: str, is_finished):
    """
    Polls the FrameStore for `key` and yields it as a standard MJPEG
    (multipart/x-mixed-replace) stream — the format browsers have natively
    displayed live camera feeds in via a plain <img> tag for decades, no
    WebSocket/canvas code needed on the client.

    Polling at 10/s caps how often we re-send the same frame if processing
    is slower than that; it never waits on the processing thread directly.
    """
    boundary = b"--frame"
    while True:
        jpeg_bytes = frame_store.get(key)
        if jpeg_bytes is not None:
            yield (
                boundary
                + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(jpeg_bytes)).encode()
                + b"\r\n\r\n"
                + jpeg_bytes
                + b"\r\n"
            )
        if is_finished():
            break
        time.sleep(0.1)


# ---------------------------------------------------------------- videos --

def _process_upload_job(job_id: str, path: Path):
    source = VideoSource(source_id=f"upload-{job_id}", location=str(path), is_stream=False)

    def on_frame(frame, tracked):
        upload_jobs[job_id]["frames_processed"] = frame.index + 1
        annotated = draw_detections(frame.image, tracked)
        jpeg_bytes = encode_jpeg(annotated)
        if jpeg_bytes is not None:
            frame_store.set(f"upload:{job_id}", jpeg_bytes)

    try:
        run_pipeline(source, detector, counter, on_frame=on_frame)
        upload_jobs[job_id]["status"] = "completed"
        upload_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
    except Exception as exc:  # noqa: BLE001 - report any failure back via status endpoint
        logger.exception("Upload job %s failed", job_id)
        upload_jobs[job_id]["status"] = "failed"
        upload_jobs[job_id]["error"] = str(exc)


@app.post("/api/videos/upload")
def upload_video(file: UploadFile):
    job_id = str(uuid.uuid4())
    dest_path = UPLOAD_DIR / f"{job_id}_{file.filename}"
    with open(dest_path, "wb") as f:
        f.write(file.file.read())

    upload_jobs[job_id] = {
        "job_id": job_id,
        "filename": file.filename,
        "status": "processing",
        "frames_processed": 0,
        "started_at": datetime.utcnow().isoformat(),
    }
    thread = threading.Thread(
        target=_process_upload_job, args=(job_id, dest_path), daemon=True
    )
    thread.start()
    return {"job_id": job_id, "status": "processing"}


@app.get("/api/videos/{job_id}/status")
def get_upload_status(job_id: str):
    job = upload_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return job


@app.get("/api/videos/{job_id}/preview")
def preview_upload(job_id: str):
    if job_id not in upload_jobs:
        raise HTTPException(status_code=404, detail="Unknown job_id")

    def is_finished():
        return upload_jobs[job_id]["status"] in ("completed", "failed")

    return StreamingResponse(
        _mjpeg_stream(f"upload:{job_id}", is_finished),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# --------------------------------------------------------------- streams --

def _process_stream(stream_id: str, source: VideoSource):
    def on_frame(frame, tracked):
        active_streams[stream_id]["frames_processed"] = frame.index + 1
        annotated = draw_detections(frame.image, tracked)
        jpeg_bytes = encode_jpeg(annotated)
        if jpeg_bytes is not None:
            frame_store.set(f"stream:{stream_id}", jpeg_bytes)

    def should_stop():
        return active_streams[stream_id]["status"] == "stopping"

    try:
        run_pipeline(source, detector, counter, on_frame=on_frame, should_stop=should_stop)
        active_streams[stream_id]["status"] = "stopped"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Stream %s failed", stream_id)
        active_streams[stream_id]["status"] = "failed"
        active_streams[stream_id]["error"] = str(exc)


@app.post("/api/streams")
def create_stream(req: StreamCreateRequest):
    stream_id = str(uuid.uuid4())
    source = VideoSource(source_id=f"stream-{stream_id}", location=req.url, is_stream=True)
    _stream_sources[stream_id] = source

    active_streams[stream_id] = {
        "stream_id": stream_id,
        "name": req.name,
        "url": req.url,
        "status": "running",
        "frames_processed": 0,
        "started_at": datetime.utcnow().isoformat(),
    }
    thread = threading.Thread(target=_process_stream, args=(stream_id, source), daemon=True)
    thread.start()
    return active_streams[stream_id]


@app.get("/api/streams")
def list_streams():
    return list(active_streams.values())


@app.delete("/api/streams/{stream_id}")
def stop_stream(stream_id: str):
    if stream_id not in active_streams:
        raise HTTPException(status_code=404, detail="Unknown stream_id")
    active_streams[stream_id]["status"] = "stopping"
    source = _stream_sources.get(stream_id)
    if source is not None:
        source.stop()
    return {"stream_id": stream_id, "status": "stopping"}


@app.get("/api/streams/{stream_id}/preview")
def preview_stream(stream_id: str):
    if stream_id not in active_streams:
        raise HTTPException(status_code=404, detail="Unknown stream_id")

    def is_finished():
        return active_streams[stream_id]["status"] in ("stopped", "failed")

    return StreamingResponse(
        _mjpeg_stream(f"stream:{stream_id}", is_finished),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------- counts --

@app.get("/api/counts/live")
def get_live_counts():
    session = SessionLocal()
    try:
        today = date_type.today()
        rows = (
            session.query(VehicleType.name, DailyVehicleCount.count)
            .join(DailyVehicleCount, DailyVehicleCount.vehicle_type_id == VehicleType.id)
            .filter(DailyVehicleCount.date == today)
            .all()
        )
        counts = {name: count for name, count in rows}
        return {
            "date": today.isoformat(),
            "counts": counts,
            "total": sum(counts.values()),
        }
    finally:
        session.close()


@app.get("/api/counts/history")
def get_history(date: Optional[str] = None):
    session = SessionLocal()
    try:
        query = session.query(
            DailyVehicleCount.date, VehicleType.name, DailyVehicleCount.count
        ).join(VehicleType, DailyVehicleCount.vehicle_type_id == VehicleType.id)

        if date:
            try:
                parsed = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
            query = query.filter(DailyVehicleCount.date == parsed)

        rows = query.order_by(DailyVehicleCount.date.desc()).all()

        by_date: dict[str, dict] = {}
        for d, vehicle_type, count in rows:
            key = d.isoformat()
            by_date.setdefault(key, {"date": key, "counts": {}, "total": 0})
            by_date[key]["counts"][vehicle_type] = count
            by_date[key]["total"] += count

        return list(by_date.values())
    finally:
        session.close()


@app.get("/api/vehicle-types")
def get_vehicle_types():
    session = SessionLocal()
    try:
        rows = session.query(VehicleType).order_by(VehicleType.first_seen_at).all()
        return [
            {"name": r.name, "first_seen_at": r.first_seen_at.isoformat()} for r in rows
        ]
    finally:
        session.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the dashboard's static files last, so /api/* routes above always win.
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
