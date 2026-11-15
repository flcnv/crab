from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.db.models import FrameAnalysisRow, FrameRow, JobRow, LLMCallRow, ReportRow
from app.domain.errors import JobNotFoundError
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


class SqlJobRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def create(self, job_id: UUID, media_kind: MediaKind, upload_keys: list[str]) -> Job:
        row = JobRow(
            id=job_id,
            status=JobStatus.QUEUED,
            media_kind=media_kind,
            upload_keys=upload_keys,
            stage_timings_s={},
        )
        async with self._sm.begin() as s:
            s.add(row)
            await s.flush()
            await s.refresh(row)
            return _to_job(row, cost_usd=0.0)

    async def get(self, job_id: UUID) -> Job | None:
        async with self._sm() as s:
            row = await s.get(JobRow, job_id)
            if row is None:
                return None
            cost = await s.scalar(
                select(func.coalesce(func.sum(LLMCallRow.cost_usd), 0.0)).where(
                    LLMCallRow.job_id == job_id
                )
            )
            return _to_job(row, cost_usd=float(cost or 0.0))

    async def set_status(self, job_id: UUID, status: JobStatus, error: str | None = None) -> None:
        await self._update_job(job_id, status=status, error=error)

    async def requeue_failed(self, job_id: UUID) -> bool:
        async with self._sm.begin() as s:
            result = await s.execute(
                update(JobRow)
                .where(JobRow.id == job_id, JobRow.status == JobStatus.FAILED)
                .values(status=JobStatus.QUEUED, error=None)
                .returning(JobRow.id)
            )
            if result.scalar_one_or_none() is not None:
                return True
            await self._require_job(s, job_id)
            return False

    async def record_stage_timing(self, job_id: UUID, stage: str, seconds: float) -> None:
        merged = JobRow.stage_timings_s.op("||")(literal({stage: seconds}, type_=JSONB))
        await self._update_job(job_id, stage_timings_s=merged)

    async def save_metadata(self, job_id: UUID, metadata: MediaMetadata) -> None:
        await self._update_job(job_id, media_metadata=metadata.model_dump(mode="json"))

    async def _update_job(self, job_id: UUID, **values: Any) -> None:
        async with self._sm.begin() as s:
            result = await s.execute(
                update(JobRow).where(JobRow.id == job_id).values(**values).returning(JobRow.id)
            )
            if result.scalar_one_or_none() is None:
                raise JobNotFoundError(job_id)

    async def save_frames(self, job_id: UUID, frames: list[Frame]) -> None:
        async with self._sm.begin() as s:
            await self._require_job(s, job_id)
            await s.execute(delete(FrameRow).where(FrameRow.job_id == job_id))
            s.add_all(
                FrameRow(
                    job_id=job_id,
                    frame_id=f.frame_id,
                    storage_key=f.storage_key,
                    timestamp_s=f.timestamp_s,
                    sharpness=f.sharpness,
                )
                for f in frames
            )

    async def get_frames(self, job_id: UUID) -> list[Frame]:
        async with self._sm() as s:
            rows = await s.scalars(
                select(FrameRow).where(FrameRow.job_id == job_id).order_by(FrameRow.frame_id)
            )
            return [
                Frame(
                    frame_id=r.frame_id,
                    storage_key=r.storage_key,
                    timestamp_s=r.timestamp_s,
                    sharpness=r.sharpness,
                )
                for r in rows
            ]

    async def save_analysis(self, job_id: UUID, analysis: FrameAnalysis) -> None:
        await self._upsert_analysis(
            job_id,
            analysis.frame_id,
            status="ok",
            analysis=analysis.model_dump(mode="json"),
            error=None,
        )

    async def mark_frame_failed(self, job_id: UUID, frame_id: str, error: str) -> None:
        await self._upsert_analysis(job_id, frame_id, status="failed", analysis=None, error=error)

    async def _upsert_analysis(self, job_id: UUID, frame_id: str, **values: Any) -> None:
        stmt = insert(FrameAnalysisRow).values(job_id=job_id, frame_id=frame_id, **values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[FrameAnalysisRow.job_id, FrameAnalysisRow.frame_id],
            set_={**values, "updated_at": func.now()},
        )
        async with self._sm.begin() as s:
            await s.execute(stmt)

    async def get_analyses(self, job_id: UUID) -> list[FrameAnalysis]:
        async with self._sm() as s:
            rows = await s.scalars(
                select(FrameAnalysisRow.analysis)
                .where(FrameAnalysisRow.job_id == job_id, FrameAnalysisRow.status == "ok")
                .order_by(FrameAnalysisRow.frame_id)
            )
            return [FrameAnalysis.model_validate(a) for a in rows]

    async def record_llm_usage(
        self, job_id: UUID, stage: str, usage: LLMUsage, frame_id: str | None = None
    ) -> None:
        async with self._sm.begin() as s:
            s.add(LLMCallRow(job_id=job_id, stage=stage, frame_id=frame_id, **usage.model_dump()))

    async def save_report(self, job_id: UUID, report: TrenchReport) -> None:
        data = report.model_dump(mode="json")
        stmt = insert(ReportRow).values(job_id=job_id, report=data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ReportRow.job_id], set_={"report": data, "updated_at": func.now()}
        )
        async with self._sm.begin() as s:
            await s.execute(stmt)

    async def get_report(self, job_id: UUID) -> TrenchReport | None:
        async with self._sm() as s:
            data = await s.scalar(select(ReportRow.report).where(ReportRow.job_id == job_id))
            return None if data is None else TrenchReport.model_validate(data)

    @staticmethod
    async def _require_job(s: AsyncSession, job_id: UUID) -> None:
        if await s.get(JobRow, job_id) is None:
            raise JobNotFoundError(job_id)


def _to_job(row: JobRow, cost_usd: float) -> Job:
    return Job(
        id=row.id,
        status=row.status,
        media_kind=row.media_kind,
        upload_keys=row.upload_keys,
        metadata=(MediaMetadata.model_validate(row.media_metadata) if row.media_metadata else None),
        error=row.error,
        stage_timings_s=row.stage_timings_s,
        cost_usd=cost_usd,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
