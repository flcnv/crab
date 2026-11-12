"""API request/response models (separate from domain models)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.models import JobStatus


class JobCreated(BaseModel):
    job_id: UUID


class JobOut(BaseModel):
    job_id: UUID
    status: JobStatus
    created_at: datetime
    stage_timings_s: dict[str, float] = {}
    cost_usd: float = 0.0
    error: str | None = None
