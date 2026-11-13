# Trench Report Agent

Upload a video or photos of an open utility trench and get back a structured documentation
report: which utilities are visible (gas, water, sewer, district heating, power, telecom),
their material and size, how confident the system is, and how accurate the pipeline is on a
labeled eval set.

> Semantic extraction from 2D images only, no 3D reconstruction or survey-grade geometry.

## Architecture

Hexagonal (ports & adapters): the domain (`app/domain`) holds models, rules and port
interfaces and imports no framework, database, queue or LLM SDK. Adapters implement the ports;
`app/bootstrap.py` is the single place that wires them together for both entrypoints.

```
            +-----------+     enqueue      +---------+
 client --> |  FastAPI  | ---------------> |  Redis  |
            |   (api)   | <-- job status   |  (arq)  |
            +-----------+                  +----+----+
                  |                             |
                  v                             v
            +-----------+                +-------------+
            | Postgres  | <------------- |   worker    |
            | jobs,     |   results      |  pipeline   |
            | frames    |                +------+------+
            +-----------+                       |
                                    +-----------+-----------+
                                    v           v           v
                              FrameExtractor  VisionModel  Storage
                              (ffmpeg, cv2)   (Claude)     (local fs)
```

### Pipeline

Job states: `queued -> extracting -> analyzing -> consolidating -> verifying -> done | failed`.

| Stage | What it does |
|-------|--------------|
| `ingest` | Duration, resolution, capture time and GPS: `ffprobe` for videos (incl. phone ISO 6709 location and rotation), EXIF for photos |
| `extract_frames` | Video: sample 1 fps, drop blurry frames, drop near-duplicates, keep the best 12. Photos: fix EXIF rotation, downscale to 1500 px |
| `analyze_frames` | Claude vision call per frame -> typed `FrameAnalysis` |
| `consolidate` | Tool-use agent merges per-frame findings into distinct physical lines |
| `verify` | Independent pass flags claims not supported by the frames |
| `render` | JSON (source of truth), Markdown, GeoJSON |

Every stage is idempotent and skips work that is already stored, so re-running a failed job
resumes where it stopped. A failing stage marks the job `failed` with `"<stage>: <reason>"`
and never crashes the worker. Per-stage timings are recorded on the job.

### Keyframe selection

The model should see few, sharp, distinct frames, not 30 near-identical ones.

1. `ffmpeg` samples frames (rotation from the phone's display matrix is applied).
2. **Sharpness** = variance of the Laplacian (OpenCV) on a 640 px wide grayscale copy, so the
   threshold does not depend on resolution. Blurry frames are dropped; if all are blurry,
   the sharpest one is kept.
3. **Near-duplicates**: 64-bit difference hash (dHash); frames closer than 6 bits count as
   duplicates.
4. Greedy pick, sharpest first, so the sharper copy of a duplicate pair wins; capped at
   `MAX_FRAMES` and returned in time order.

Measuring happens in the adapter; the selection rule is pure domain code
(`app/domain/services/keyframes.py`) with its own unit tests.

## API

| Method | Path | Result |
|--------|------|--------|
| `POST` | `/jobs` | multipart `files`: one video **or** 1-50 photos -> `202 {job_id, status, status_url}` |
| `GET` | `/jobs/{id}` | status, media kind, error, stage timings, cost |
| `GET` | `/jobs/{id}/report` | `TrenchReport` JSON; `409` while the job is still running |
| `GET` | `/jobs/{id}/report.md` | human-readable Markdown report |
| `GET` | `/health` | liveness |

Accepted files: `.mp4 .mov .m4v .webm` or `.jpg .jpeg .png .webp`, up to 500 MB per job.
Errors: `404` unknown job, `413` too large, `422` invalid upload (wrong type, video + photos mixed).

```bash
curl -F "files=@trench.mp4" localhost:8000/jobs
curl -F "files=@a.jpg" -F "files=@b.jpg" localhost:8000/jobs
curl localhost:8000/jobs/<job_id>
```

## Data

Postgres tables: `jobs` (status, metadata, timings), `frames`, `frame_analyses` (JSONB of the
domain model, `ok`/`failed` per frame), `reports` (JSONB), `llm_calls` (tokens, cost, latency,
model and prompt version of every model call; a job's cost is their sum). Files live in
`storage/`: `uploads/<job_id>/...` and `frames/<job_id>/fNNN.jpg`.

## Run it

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY
docker compose up --build     # postgres, redis, migrate, api, worker
curl localhost:8000/health
```

`migrate` applies Alembic migrations before `api` and `worker` start.

## Development

```bash
uv sync
uv run pre-commit install     # ruff, mypy, uv-lock on commit; pytest on push
uv run pytest                 # DB/Redis tests need `docker compose up postgres redis`
```

- Tests: unit tests for domain rules, API tests with in-memory fakes of the ports,
  integration tests against real Postgres, Redis and ffmpeg (skipped when unavailable).
- CI (GitHub Actions): ruff, mypy, tests with Postgres + Redis services and ffmpeg,
  migration check (`alembic upgrade` -> `alembic check` -> `downgrade`), Docker build.

### Python 3.15 features used

- `lazy import` for cv2, numpy, imagehash and Pillow: the API process never loads them.
- `frozendict` for constant mappings (accepted file types, error -> HTTP status).
- `uuid.uuid7()` for job ids: time-ordered, so the primary key index stays compact.

## Project layout

```
app/
  domain/      models/, ports/, services/, errors/   pure, no I/O
  adapters/    db/, queue/, storage/, media/, llm/, render/
  api/         FastAPI app, routes, error mapping
  worker/      arq settings, pipeline
  bootstrap.py composition root
migrations/    Alembic
tests/
eval/          labeled eval set and metrics
```

## Limitations

- No absolute scale from a single image: diameter and depth stay `null` unless a reference
  (folding ruler, tape measure) is visible.
- No 3D reconstruction or metric survey; production systems use LiDAR / photogrammetry for that.
- Storage is the local filesystem (the `Storage` port is ready for S3).
