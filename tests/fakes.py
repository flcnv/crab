from datetime import UTC, datetime
from uuid import UUID

from app.domain.errors import JobNotFoundError
from app.domain.models import (
    RUNNING_STATUSES,
    Frame,
    FrameAnalysis,
    Job,
    JobStatus,
    LLMUsage,
    MediaKind,
    MediaMetadata,
    TrenchReport,
)


class InMemoryJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[UUID, Job] = {}
        self.frames: dict[UUID, list[Frame]] = {}
        self.analyses: dict[UUID, dict[str, FrameAnalysis | str]] = {}
        self.usage: dict[UUID, list[tuple[str, LLMUsage, str | None]]] = {}
        self.reports: dict[UUID, TrenchReport] = {}

    def _require(self, job_id: UUID) -> Job:
        if job_id not in self.jobs:
            raise JobNotFoundError(job_id)
        return self.jobs[job_id]

    def _update(self, job_id: UUID, **changes: object) -> None:
        job = self._require(job_id)
        self.jobs[job_id] = job.model_copy(update={**changes, "updated_at": datetime.now(UTC)})

    async def create(self, job_id: UUID, media_kind: MediaKind, upload_keys: list[str]) -> Job:
        now = datetime.now(UTC)
        job = Job(
            id=job_id,
            status=JobStatus.QUEUED,
            media_kind=media_kind,
            upload_keys=upload_keys,
            created_at=now,
            updated_at=now,
        )
        self.jobs[job_id] = job
        return job

    async def get(self, job_id: UUID) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        cost = sum(u.cost_usd for _, u, _ in self.usage.get(job_id, []))
        return job.model_copy(update={"cost_usd": cost})

    async def set_status(self, job_id: UUID, status: JobStatus, error: str | None = None) -> None:
        self._update(job_id, status=status, error=error)

    async def requeue_for_retry(self, job_id: UUID, stale_before: datetime) -> bool:
        job = self._require(job_id)
        stalled = job.status in RUNNING_STATUSES and job.updated_at < stale_before
        if job.status is not JobStatus.FAILED and not stalled:
            return False
        self._update(job_id, status=JobStatus.QUEUED, error=None)
        return True

    async def record_stage_timing(self, job_id: UUID, stage: str, seconds: float) -> None:
        job = self._require(job_id)
        self._update(job_id, stage_timings_s={**job.stage_timings_s, stage: seconds})

    async def save_metadata(self, job_id: UUID, metadata: MediaMetadata) -> None:
        self._update(job_id, metadata=metadata)

    async def save_frames(self, job_id: UUID, frames: list[Frame]) -> None:
        self._require(job_id)
        self.frames[job_id] = sorted(frames, key=lambda f: f.frame_id)
        self.analyses[job_id] = {}

    async def get_frames(self, job_id: UUID) -> list[Frame]:
        return list(self.frames.get(job_id, []))

    async def save_analysis(self, job_id: UUID, analysis: FrameAnalysis) -> None:
        self.analyses.setdefault(job_id, {})[analysis.frame_id] = analysis

    async def mark_frame_failed(self, job_id: UUID, frame_id: str, error: str) -> None:
        self.analyses.setdefault(job_id, {})[frame_id] = error

    async def get_analyses(self, job_id: UUID) -> list[FrameAnalysis]:
        items = sorted(self.analyses.get(job_id, {}).items())
        return [a for _, a in items if isinstance(a, FrameAnalysis)]

    async def record_llm_usage(
        self, job_id: UUID, stage: str, usage: LLMUsage, frame_id: str | None = None
    ) -> None:
        self.usage.setdefault(job_id, []).append((stage, usage, frame_id))

    async def save_report(self, job_id: UUID, report: TrenchReport) -> None:
        self.reports[job_id] = report

    async def get_report(self, job_id: UUID) -> TrenchReport | None:
        return self.reports.get(job_id)


class FakeJobQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.enqueued: list[UUID] = []
        self.fail = fail

    async def enqueue(self, job_id: UUID) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.enqueued.append(job_id)

    async def aclose(self) -> None:
        pass
