# Vehicle Detection & Counting System

Detects and classifies vehicles from an uploaded video or a live camera
stream, counts each unique vehicle once, keeps a running vehicle-type
registry, and retains full date-wise history — all behind a REST API with
a small live dashboard.

## Architecture

```
[Video upload]   [Live camera stream]
        \                /
         v              v
           Ingestion layer         (ingestion/)
                 |
                 v
           Detector (YOLOv8)       (detection/)
                 |
                 v
           Tracker (ByteTrack)     (tracking/)
                 |
                 v
           Counter / Aggregator    (counting/)
                 |
                 v
           Database                (storage/)
              /              \
             v                v
        Scheduler          API layer (FastAPI)   (scheduler/, api/)
                                 |
                                 v
                            Dashboard              (ui/)
```

Each stage only talks to the next through a small, explicit interface
(`FrameSource`, `Detector`, tracked-detection lists). This makes the
system modular: swapping the detection model, adding a second tracker
option, or adding a brand-new feature (speed estimation, license-plate
OCR, zone-based directional counting, multi-camera support) means adding a
new module behind an existing interface, not touching the others.

## Key design decisions & v1 assumptions

These were chosen deliberately for the current (single-camera, POC) scope
— worth revisiting if requirements grow:

- **Counting rule**: a vehicle is counted the moment its tracked ID is
  first seen, not when it crosses a line/zone. Simpler, matches the
  original ask. Revisit if directional/zone-based counting is needed.
- **"New vehicle type"**: means a class the YOLOv8 model already knows
  (car, truck, bus, motorcycle, bicycle) appearing for the first time in
   data — not open-vocabulary detection of unknown vehicle types.
- **Date-keyed counts, no explicit "reset" step**: counts are stored as
  `(date, vehicle_type, count)`. Today's counts ARE the row where
  `date = today`; when the date rolls over, new counts simply land under
  a new key. There's nothing to migrate at midnight, so there's no
  reset job that can fail or double-run.
- **In-memory job/stream state**: upload job status and active-stream
  state live in memory, not the database. If the API process restarts,
  in-flight jobs/streams are lost (though already-counted vehicles stay in
  the database). Fine for a single-instance POC; a job queue (Celery/RQ)
  is the natural upgrade for durability and multi-instance scale.
- **Track IDs reset per run**: a fresh tracker is created each time a
  video/stream starts. If a stream restarts, a vehicle still in frame
  could be counted again — a known v1 limitation, not a bug.
- **supervision's `ByteTrack`** is flagged deprecated upstream (as of
  `supervision` 0.30.0) but still fully functional; `requirements.txt`
  pins `supervision<0.31.0` so this doesn't break underfoot. Revisit the
  pin when upgrading.

## Project layout

```
ingestion/    FrameSource interface + VideoSource (handles upload file AND stream URL)
detection/    Detector interface + YOLOv8 implementation
tracking/     Assigns persistent IDs across frames (ByteTrack)
counting/     Counts each unique vehicle once, maintains the vehicle-type registry
storage/      SQLAlchemy models + DB session (SQLite locally, Postgres via Docker)
scheduler/    Daily summary hook (see design note above)
pipeline/     Wires ingestion -> detection -> tracking -> counting together
api/          FastAPI app (all HTTP endpoints)
ui/           Static dashboard (served by the API, no build step)
tests/        Standalone demo script used while building the pipeline
sample_data/  A real sample image + a generated test clip, for smoke-testing
```

## API reference

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/videos/upload` | Upload a video file for processing (multipart `file`) |
| GET | `/api/videos/{job_id}/status` | Poll processing progress/result |
| POST | `/api/streams` | Start watching a live camera (`{"name": ..., "url": ...}`) |
| GET | `/api/streams` | List active/stopped streams |
| DELETE | `/api/streams/{stream_id}` | Stop a running stream |
| GET | `/api/counts/live` | Today's counts by vehicle type |
| GET | `/api/counts/history?date=YYYY-MM-DD` | Historical counts (all dates if omitted) |
| GET | `/api/vehicle-types` | Registry of known vehicle types + first-seen date |
| GET | `/api/health` | Health check |

The dashboard at `/` (served by the same app) uses all of the above — the
"Upload video" / "Watch a live camera" forms just call these endpoints and
poll for status.

---

## How to run it

### Option A — Local, no Docker (fastest way to try it)

Requires Python 3.11+.

```bash
cd vehicle_detection
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Then open **http://localhost:8000** in a browser — that's the dashboard.
The API itself is under `http://localhost:8000/api/...`.

This uses a local SQLite file (`vehicle_detection.db`, created
automatically) — nothing else to set up. The first request that runs
detection will auto-download the YOLOv8n weights (~6 MB) from Ultralytics.

To try it immediately without a real camera, use the bundled sample clip:

```bash
curl -X POST http://localhost:8000/api/videos/upload -F "file=@sample_data/test_clip.mp4"
```

### Option B — Docker (matches a real deployment)

Requires Docker and Docker Compose.

```bash
cd vehicle_detection
docker compose up --build
```

This starts two containers:
- `db` — Postgres 16 (data persisted in a named volume)
- `app` — the FastAPI app on port 8000, connected to Postgres via
  `DATABASE_URL` (already wired in `docker-compose.yml`)

Open **http://localhost:8000** once both containers report healthy.

Stop everything with:
```bash
docker compose down
```
(add `-v` to also delete the Postgres volume and start fresh)

### Connecting a real camera

In the dashboard's "Watch a live camera" form (or via `POST /api/streams`),
give it a name and the camera's stream URL, e.g.:
- `rtsp://username:password@camera-ip:554/stream1`
- `http://camera-ip/video` (for MJPEG-style HTTP cameras)

Anything `cv2.VideoCapture` can open will work, since that's what
`ingestion/video_source.py` uses under the hood — the same class handles
both this and file uploads.

### Running the original step-1 demo script

Kept from the earlier build-out for quick sanity checks against any video
file, independent of the API:

```bash
python3 tests/demo_ingestion_and_detection.py path/to/video.mp4
```
