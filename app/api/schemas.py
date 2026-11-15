from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel

from app.domain.models import Job, JobStatus, MediaKind


class JobCreated(BaseModel):
    job_id: UUID
    status: JobStatus
    status_url: str


class JobOut(BaseModel):
    job_id: UUID
    status: JobStatus
    media_kind: MediaKind
    file_count: int
    error: str | None
    stage_timings_s: dict[str, float]
    cost_usd: float
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, job: Job) -> Self:
        return cls(
            job_id=job.id,
            status=job.status,
            media_kind=job.media_kind,
            file_count=len(job.upload_keys),
            error=job.error,
            stage_timings_s=job.stage_timings_s,
            cost_usd=job.cost_usd,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
