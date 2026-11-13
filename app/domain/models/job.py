from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.models.enums import JobStatus
from app.domain.models.media import MediaKind, MediaMetadata


class Job(BaseModel):
    """One processing job: an upload (video or photos) and its pipeline state."""

    id: UUID
    status: JobStatus
    media_kind: MediaKind
    upload_keys: list[str]
    metadata: MediaMetadata | None = None
    error: str | None = None
    stage_timings_s: dict[str, float] = Field(default_factory=dict)
    cost_usd: float = 0.0
    created_at: datetime
    updated_at: datetime
