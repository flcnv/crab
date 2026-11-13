import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.db.repositories import SqlJobRepository
from app.domain.errors import JobNotFoundError
from app.domain.models import (
    Evidence,
    Frame,
    FrameAnalysis,
    JobStatus,
    LineObservation,
    LLMUsage,
    Material,
    MediaMetadata,
    ReportLine,
    TrenchReport,
    UtilityType,
)


@pytest.fixture
def repo(sessionmaker: async_sessionmaker[AsyncSession]) -> SqlJobRepository:
    return SqlJobRepository(sessionmaker)


def _analysis(frame_id: str, confidence: float = 0.7) -> FrameAnalysis:
    return FrameAnalysis(
        frame_id=frame_id,
        is_trench_visible=True,
        scale_reference_visible=False,
        warning_tapes=["yellow: Achtung Gasleitung"],
        lines=[
            LineObservation(
                utility_type=UtilityType.GAS,
                material=Material.PE,
                color="yellow",
                approx_outer_diameter_mm=None,
                approx_depth_of_cover_m=None,
                is_house_connection=None,
                evidence=[Evidence(cue="warning_tape_text", detail="Achtung Gasleitung")],
                confidence=confidence,
            )
        ],
        image_quality_issues=[],
    )


def _usage(cost: float) -> LLMUsage:
    return LLMUsage(
        model="claude-sonnet-5-5",
        prompt_version="v1",
        input_tokens=1000,
        output_tokens=200,
        cost_usd=cost,
        latency_s=1.5,
    )


async def _job_with_frames(repo: SqlJobRepository, *frame_ids: str) -> uuid.UUID:
    job = await repo.create(uuid.uuid4(), "video", ["uploads/a.mp4"])
    await repo.save_frames(
        job.id, [Frame(frame_id=f, storage_key=f"frames/{f}.jpg") for f in frame_ids]
    )
    return job.id


async def test_create_and_get(repo: SqlJobRepository) -> None:
    job = await repo.create(uuid.uuid4(), "image", ["uploads/1.jpg", "uploads/2.jpg"])

    assert job.status is JobStatus.QUEUED
    assert job.cost_usd == 0.0
    assert await repo.get(job.id) == job


async def test_get_unknown_returns_none(repo: SqlJobRepository) -> None:
    assert await repo.get(uuid.uuid4()) is None


async def test_status_metadata_and_timings(repo: SqlJobRepository) -> None:
    job = await repo.create(uuid.uuid4(), "video", ["uploads/a.mp4"])

    await repo.set_status(job.id, JobStatus.FAILED, error="boom")
    await repo.save_metadata(job.id, MediaMetadata(kind="video", duration_s=12.5))
    await repo.record_stage_timing(job.id, "extract_frames", 1.2)
    await repo.record_stage_timing(job.id, "analyze_frames", 8.0)

    got = await repo.get(job.id)
    assert got is not None
    assert got.status is JobStatus.FAILED
    assert got.error == "boom"
    assert got.metadata == MediaMetadata(kind="video", duration_s=12.5)
    assert got.stage_timings_s == {"extract_frames": 1.2, "analyze_frames": 8.0}


async def test_updates_on_unknown_job_raise(repo: SqlJobRepository) -> None:
    with pytest.raises(JobNotFoundError):
        await repo.set_status(uuid.uuid4(), JobStatus.DONE)
    with pytest.raises(JobNotFoundError):
        await repo.save_frames(uuid.uuid4(), [])


async def test_save_frames_replaces_and_drops_old_analyses(repo: SqlJobRepository) -> None:
    job_id = await _job_with_frames(repo, "f001", "f002")
    await repo.save_analysis(job_id, _analysis("f001"))

    await repo.save_frames(job_id, [Frame(frame_id="f003", storage_key="frames/f003.jpg")])

    assert [f.frame_id for f in await repo.get_frames(job_id)] == ["f003"]
    assert await repo.get_analyses(job_id) == []


async def test_analysis_upsert_and_failed_frames(repo: SqlJobRepository) -> None:
    job_id = await _job_with_frames(repo, "f001", "f002")

    await repo.save_analysis(job_id, _analysis("f002", confidence=0.4))
    await repo.save_analysis(job_id, _analysis("f002", confidence=0.9))  # upsert
    await repo.mark_frame_failed(job_id, "f001", "validation error")

    analyses = await repo.get_analyses(job_id)
    assert [a.frame_id for a in analyses] == ["f002"]
    assert analyses[0].lines[0].confidence == 0.9


async def test_llm_usage_sums_into_job_cost(repo: SqlJobRepository) -> None:
    job_id = await _job_with_frames(repo, "f001")

    await repo.record_llm_usage(job_id, "analyze_frames", _usage(0.01), frame_id="f001")
    await repo.record_llm_usage(job_id, "consolidate", _usage(0.03))

    got = await repo.get(job_id)
    assert got is not None
    assert got.cost_usd == pytest.approx(0.04)


async def test_report_roundtrip_and_overwrite(repo: SqlJobRepository) -> None:
    job = await repo.create(uuid.uuid4(), "video", ["uploads/a.mp4"])
    assert await repo.get_report(job.id) is None

    line = ReportLine(
        id="L1",
        utility_type=UtilityType.GAS,
        material=Material.PE,
        approx_outer_diameter_mm=None,
        approx_depth_of_cover_m=None,
        seen_in_frames=["f001"],
        confidence=0.8,
        notes=None,
    )
    report = TrenchReport(
        job_id=job.id, lines=[line], verification_flags=[], limitations=[], location=None
    )
    await repo.save_report(job.id, report)
    flagged = report.model_copy(update={"verification_flags": ["L1: depth unsupported"]})
    await repo.save_report(job.id, flagged)

    assert await repo.get_report(job.id) == flagged
