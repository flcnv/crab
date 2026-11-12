# CRAB - Trench Report Agent

Upload a video or photos of an open utility trench and get back a structured documentation
report: which utilities are visible (gas, water, sewer, district heating, power, telecom),
their material and size, how confident the system is, and how accurate the pipeline is on a
labeled eval set.

> Weekend prototype. Semantic extraction from 2D images only, no 3D reconstruction or survey-grade geometry.

## Stack

FastAPI, arq + Redis, Postgres (SQLAlchemy async + Alembic), Claude vision models via the
`anthropic` SDK, ffmpeg/Pillow for frames. Python 3.15, managed with `uv`.

## Quick start

```bash
cp .env.example .env   # set ANTHROPIC_API_KEY
docker compose up --build
curl localhost:8000/health
```

Work in progress.
