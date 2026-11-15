from typing import Protocol
from uuid import UUID

from app.domain.models import (
    Frame,
    FrameAnalysis,
    Job,
    JobStatus,
    LLMUsage,
    MediaKind,
    MediaMetadata,
    TrenchReport,
)


class JobRepository(Protocol):
    """Persistence for jobs and every pipeline stage output (stages are idempotent).

    Methods that update an existing job raise `JobNotFoundError` if it does not exist.
    """

    async def create(self, job_id: UUID, media_kind: MediaKind, upload_keys: list[str]) -> Job: ...
    async def get(self, job_id: UUID) -> Job | None: ...
    async def set_status(
        self, job_id: UUID, status: JobStatus, error: str | None = None
    ) -> None: ...
    async def requeue_failed(self, job_id: UUID) -> bool:
        """Atomically move a `failed` job back to `queued` and clear its error.

        Returns False (and changes nothing) if the job is in any other status, so two
        concurrent retries cannot both re-run it and a running job cannot be restarted.
        """
        ...

    async def record_stage_timing(self, job_id: UUID, stage: str, seconds: float) -> None: ...
    async def save_metadata(self, job_id: UUID, metadata: MediaMetadata) -> None: ...

    async def save_frames(self, job_id: UUID, frames: list[Frame]) -> None:
        """Replace all frames of the job (re-running extraction is safe)."""
        ...

    async def get_frames(self, job_id: UUID) -> list[Frame]: ...

    async def save_analysis(self, job_id: UUID, analysis: FrameAnalysis) -> None:
        """Upsert by (job_id, frame_id)."""
        ...

    async def mark_frame_failed(self, job_id: UUID, frame_id: str, error: str) -> None: ...

    async def get_analyses(self, job_id: UUID) -> list[FrameAnalysis]:
        """Successful analyses only, ordered by frame_id."""
        ...

    async def record_llm_usage(
        self, job_id: UUID, stage: str, usage: LLMUsage, frame_id: str | None = None
    ) -> None: ...
    async def save_report(self, job_id: UUID, report: TrenchReport) -> None: ...
    async def get_report(self, job_id: UUID) -> TrenchReport | None: ...
