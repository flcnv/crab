import asyncio
import dataclasses
import uuid
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest

from app.adapters.storage.local import LocalStorage
from app.bootstrap import Deps, build_deps
from app.domain.errors import ConsolidationError, FrameAnalysisError, MediaProcessingError
from app.domain.models import (
    Consolidation,
    Evidence,
    ExtractedFrame,
    FrameAnalysis,
    GeoPoint,
    JobStatus,
    LineObservation,
    LLMUsage,
    Material,
    MediaKind,
    MediaMetadata,
    ObservationRef,
    ReportLine,
    ReviewReason,
    UtilityType,
    VerificationConfig,
)
from app.domain.ports.llm import ImageLoader
from app.domain.services import retry_job
from app.worker.pipeline import run_pipeline
from tests.fakes import FakeJobQueue, InMemoryJobRepository


class FakeMetadataReader:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    async def read(self, path: Path, kind: MediaKind) -> MediaMetadata:
        self.calls.append(path)
        return MediaMetadata(kind=kind, width=100, height=50, location=GeoPoint(lat=1, lon=2))


class FakeFrameExtractor:
    def __init__(self, n: int = 3, *, fail: bool = False) -> None:
        self.n, self.fail, self.calls = n, fail, 0

    async def from_video(self, video: Path, max_frames: int) -> list[ExtractedFrame]:
        self.calls += 1
        if self.fail:
            raise MediaProcessingError("ffmpeg failed: moov atom not found")
        return [
            ExtractedFrame(jpeg=f"jpeg{i}".encode(), timestamp_s=float(i), sharpness=100.0)
            for i in range(min(self.n, max_frames))
        ]

    async def from_images(self, images: list[Path]) -> list[ExtractedFrame]:
        self.calls += 1
        return [ExtractedFrame(jpeg=p.read_bytes()) for p in images]


class FakeVisionModel:
    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[str] = []
        self.active = self.max_active = 0

    async def analyze(self, image: bytes, frame_id: str) -> tuple[FrameAnalysis, list[LLMUsage]]:
        self.calls.append(frame_id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        usage = [
            LLMUsage(
                model="fake",
                prompt_version="v1",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.001,
                latency_s=0.01,
            )
        ]
        if frame_id in self.fail:
            raise FrameAnalysisError("model refused (category: None)", usage)
        line = LineObservation(
            utility_type=UtilityType.WATER,
            material=Material.PE,
            color="blue",
            approx_outer_diameter_mm=110,
            approx_depth_of_cover_m=1.2,
            is_house_connection=None,
            evidence=[Evidence(cue="color", detail="blue jacket")],
            confidence=0.5,
        )
        analysis = FrameAnalysis(
            frame_id=frame_id,
            is_trench_visible=True,
            scale_reference_visible=False,
            warning_tapes=[],
            lines=[line],
            image_quality_issues=[],
        )
        return analysis, usage


class FakeReportAgent:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail, self.calls = fail, 0
        self.images: list[bytes] = []

    async def consolidate(
        self, job_id: UUID, analyses: list[FrameAnalysis], load_image: ImageLoader
    ) -> tuple[Consolidation, list[LLMUsage]]:
        self.calls += 1
        usage = [
            LLMUsage(
                model="fake",
                prompt_version="v1",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.01,
                latency_s=1.0,
            )
        ]
        if self.fail:
            raise ConsolidationError("no valid report after 10 turns", usage)
        self.images.append(await load_image(analyses[0].frame_id))
        line = ReportLine(
            id="L1",
            utility_type=UtilityType.WATER,
            material=Material.PE,
            approx_outer_diameter_mm=None,
            approx_depth_of_cover_m=None,
            observations=[ObservationRef(frame_id=a.frame_id, line_index=0) for a in analyses],
            confidence=0.6,
            notes=None,
        )
        return Consolidation(lines=[line], remarks=["agent remark"], method="agent"), usage


@pytest.fixture
def deps(tmp_path: Path) -> Deps:
    return dataclasses.replace(
        build_deps(),
        jobs=InMemoryJobRepository(),
        queue=FakeJobQueue(),
        storage=LocalStorage(tmp_path),
        metadata_reader=FakeMetadataReader(),
        frame_extractor=FakeFrameExtractor(),
        vision_model=FakeVisionModel(),
        report_agent=FakeReportAgent(),
    )


async def _new_job(deps: Deps, kind: MediaKind, *names: str) -> UUID:
    keys = [await deps.storage.put(f"uploads/{n}", b"data-" + n.encode()) for n in names]
    return (await deps.jobs.create(uuid.uuid4(), kind, keys)).id


async def test_video_job_stores_frames_and_analyses(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    job = await deps.jobs.get(job_id)
    assert job is not None
    assert job.status is JobStatus.DONE
    assert job.error is None
    assert job.metadata is not None
    assert job.metadata.location == GeoPoint(lat=1, lon=2)
    assert set(job.stage_timings_s) == {
        "ingest",
        "extract_frames",
        "analyze_frames",
        "consolidate",
        "verify",
    }
    assert job.cost_usd == pytest.approx(0.013)

    frames = await deps.jobs.get_frames(job_id)
    assert [f.frame_id for f in frames] == ["f001", "f002", "f003"]
    assert await deps.storage.get(frames[1].storage_key) == b"jpeg1"
    assert frames[1].storage_key == f"frames/{job_id}/f002.jpg"


async def test_photo_job_uses_every_photo(deps: Deps) -> None:
    job_id = await _new_job(deps, "image", "a.jpg", "b.jpg")

    await run_pipeline(deps, job_id)

    frames = await deps.jobs.get_frames(job_id)
    assert [await deps.storage.get(f.storage_key) for f in frames] == [b"data-a.jpg", b"data-b.jpg"]
    assert isinstance(deps.metadata_reader, FakeMetadataReader)
    assert len(deps.metadata_reader.calls) == 2


async def _fail_after_the_fact(deps: Deps, job_id: UUID) -> None:
    await deps.jobs.set_status(job_id, JobStatus.FAILED, "verify: worker killed")


async def test_done_job_is_not_run_again(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    await run_pipeline(deps, job_id)
    await run_pipeline(deps, job_id)

    assert _agent(deps).calls == 1
    assert sorted(_vision(deps).calls) == ["f001", "f002", "f003"]


async def test_rerun_skips_finished_stages(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    await run_pipeline(deps, job_id)
    await _fail_after_the_fact(deps, job_id)
    await run_pipeline(deps, job_id)

    assert isinstance(deps.frame_extractor, FakeFrameExtractor)
    assert deps.frame_extractor.calls == 1
    assert isinstance(deps.metadata_reader, FakeMetadataReader)
    assert len(deps.metadata_reader.calls) == 1


async def test_media_error_fails_job_with_stage_name(deps: Deps) -> None:
    deps = dataclasses.replace(deps, frame_extractor=FakeFrameExtractor(fail=True))
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    job = await deps.jobs.get(job_id)
    assert job is not None
    assert job.status is JobStatus.FAILED
    assert job.error == "extract_frames: ffmpeg failed: moov atom not found"
    assert await deps.jobs.get_frames(job_id) == []


async def test_unknown_job_is_ignored(deps: Deps) -> None:
    await run_pipeline(deps, uuid.uuid4())


def _vision(deps: Deps) -> FakeVisionModel:
    assert isinstance(deps.vision_model, FakeVisionModel)
    return deps.vision_model


async def test_analyses_are_saved_with_sizes_stripped(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    await run_pipeline(deps, job_id)

    analyses = await deps.jobs.get_analyses(job_id)
    assert [a.frame_id for a in analyses] == ["f001", "f002", "f003"]
    line = analyses[0].lines[0]
    assert (line.approx_outer_diameter_mm, line.approx_depth_of_cover_m) == (None, None)
    assert line.utility_type is UtilityType.WATER


async def test_concurrency_is_limited(deps: Deps) -> None:
    settings = deps.settings.model_copy(update={"llm_concurrency": 2, "max_frames": 8})
    deps = dataclasses.replace(deps, settings=settings, frame_extractor=FakeFrameExtractor(n=8))
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    assert len(_vision(deps).calls) == 8
    assert _vision(deps).max_active == 2


async def test_failed_frame_is_not_fatal_and_its_cost_counts(deps: Deps) -> None:
    deps = dataclasses.replace(deps, vision_model=FakeVisionModel(fail={"f002"}))
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    job = await deps.jobs.get(job_id)
    assert job is not None
    assert job.status is JobStatus.DONE
    assert job.cost_usd == pytest.approx(0.013)
    assert [a.frame_id for a in await deps.jobs.get_analyses(job_id)] == ["f001", "f003"]


async def test_all_frames_failed_fails_the_stage(deps: Deps) -> None:
    deps = dataclasses.replace(deps, vision_model=FakeVisionModel(fail={"f001", "f002", "f003"}))
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    job = await deps.jobs.get(job_id)
    assert job is not None
    assert job.status is JobStatus.FAILED
    assert job.error == (
        "analyze_frames: no frame could be analyzed "
        "(3 failed; first: model refused (category: None))"
    )


async def test_rerun_only_retries_failed_frames(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    await run_pipeline(
        dataclasses.replace(deps, vision_model=FakeVisionModel(fail={"f002"})), job_id
    )

    await _fail_after_the_fact(deps, job_id)
    healthy = FakeVisionModel()
    await run_pipeline(dataclasses.replace(deps, vision_model=healthy), job_id)

    assert healthy.calls == ["f002"]
    assert len(await deps.jobs.get_analyses(job_id)) == 3


async def test_unexpected_error_fails_with_readable_message(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    await run_pipeline(
        dataclasses.replace(deps, vision_model=FakeVisionModel(fail={"f001", "f002", "f003"})),
        job_id,
    )
    frame = (await deps.jobs.get_frames(job_id))[0]
    deps.storage.local_path(frame.storage_key).unlink()

    await run_pipeline(deps, job_id)

    job = await deps.jobs.get(job_id)
    assert job is not None
    assert job.error is not None
    assert job.error.startswith("analyze_frames: [Errno 2]")
    assert "TaskGroup" not in job.error


def _agent(deps: Deps) -> FakeReportAgent:
    assert isinstance(deps.report_agent, FakeReportAgent)
    return deps.report_agent


async def test_report_is_saved_with_limitations(deps: Deps) -> None:
    deps = dataclasses.replace(deps, vision_model=FakeVisionModel(fail={"f003"}))
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    report = await deps.jobs.get_report(job_id)
    assert report is not None
    assert [ln.seen_in_frames for ln in report.lines] == [["f001", "f002"]]
    assert report.location == GeoPoint(lat=1, lon=2)
    assert "1 of 3 frames could not be analyzed." in report.limitations
    assert report.limitations[-1] == "agent remark"
    assert report.consolidation_method == "agent"
    assert _agent(deps).images == [b"jpeg0"]


async def test_agent_failure_falls_back_to_rules(deps: Deps) -> None:
    deps = dataclasses.replace(deps, report_agent=FakeReportAgent(fail=True))
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    report = await deps.jobs.get_report(job_id)
    assert report is not None
    [line] = report.lines
    assert line.notes == "merged by rule (color: blue)"
    assert report.consolidation_method == "rules"
    assert any("Automatic consolidation failed" in lim for lim in report.limitations)
    job = await deps.jobs.get(job_id)
    assert job is not None
    assert job.cost_usd == pytest.approx(0.013)


async def test_rerun_keeps_existing_report(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    await run_pipeline(deps, job_id)
    await _fail_after_the_fact(deps, job_id)
    await run_pipeline(deps, job_id)
    assert _agent(deps).calls == 1


async def test_job_reaches_done_with_reviews(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    report = await deps.jobs.get_report(job_id)
    assert report is not None
    [line] = report.lines
    assert line.needs_review is True
    assert [f.reason for f in line.review] == [ReviewReason.LOW_CONFIDENCE]
    assert line.review[0].detail == "confidence 0.60 <= 0.60"
    assert report.verification_flags == ["1 of 1 lines need review"]
    assert line.confidence == 0.6


async def test_rerun_recomputes_reviews_from_scratch(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    await run_pipeline(deps, job_id)
    first = await deps.jobs.get_report(job_id)
    assert first is not None

    stale = first.model_copy(
        update={
            "lines": [
                ln.model_copy(update={"needs_review": False, "review": []}) for ln in first.lines
            ],
            "verification_flags": ["stale"],
        }
    )
    await deps.jobs.save_report(job_id, stale)
    await _fail_after_the_fact(deps, job_id)
    await run_pipeline(deps, job_id)

    assert await deps.jobs.get_report(job_id) == first
    job = await deps.jobs.get(job_id)
    assert job is not None
    assert (job.status, job.error) == (JobStatus.DONE, None)


async def test_verify_uses_configured_threshold(deps: Deps) -> None:
    deps = dataclasses.replace(deps, verification=VerificationConfig(min_confidence=0.5))
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    report = await deps.jobs.get_report(job_id)
    assert report is not None
    assert report.lines[0].needs_review is False
    assert report.verification_flags == []


async def test_rules_fallback_report_is_verified_too(deps: Deps) -> None:
    deps = dataclasses.replace(deps, report_agent=FakeReportAgent(fail=True))
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    report = await deps.jobs.get_report(job_id)
    assert report is not None
    assert report.consolidation_method == "rules"
    assert [f.reason for f in report.lines[0].review] == [ReviewReason.LOW_CONFIDENCE]


async def test_retried_job_resumes_and_reaches_done(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    await run_pipeline(
        dataclasses.replace(deps, vision_model=FakeVisionModel(fail={"f001", "f002", "f003"})),
        job_id,
    )

    await retry_job(job_id, jobs=deps.jobs, queue=deps.queue, stale_after=STALE_AFTER)
    await run_pipeline(deps, job_id)

    job = await deps.jobs.get(job_id)
    assert job is not None
    assert (job.status, job.error) == (JobStatus.DONE, None)
    assert isinstance(deps.frame_extractor, FakeFrameExtractor)
    assert deps.frame_extractor.calls == 1
    assert sorted(_vision(deps).calls) == ["f001", "f002", "f003"]


STALE_AFTER = timedelta(minutes=30)


class HangingVisionModel(FakeVisionModel):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def analyze(self, image: bytes, frame_id: str) -> tuple[FrameAnalysis, list[LLMUsage]]:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


async def test_interrupted_stage_marks_job_failed_and_retry_resumes(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    hanging = dataclasses.replace(deps, vision_model=HangingVisionModel())

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(run_pipeline(hanging, job_id), timeout=0.05)

    job = await deps.jobs.get(job_id)
    assert job is not None
    assert (job.status, job.error) == (
        JobStatus.FAILED,
        "analyze_frames: interrupted (worker timeout or shutdown)",
    )

    await retry_job(job_id, jobs=deps.jobs, queue=deps.queue, stale_after=STALE_AFTER)
    await run_pipeline(deps, job_id)

    job = await deps.jobs.get(job_id)
    assert job is not None
    assert (job.status, job.error) == (JobStatus.DONE, None)
    assert isinstance(deps.frame_extractor, FakeFrameExtractor)
    assert deps.frame_extractor.calls == 1


async def test_cancelled_pipeline_is_marked_failed(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    hanging = HangingVisionModel()
    task = asyncio.create_task(
        run_pipeline(dataclasses.replace(deps, vision_model=hanging), job_id)
    )
    await hanging.started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    job = await deps.jobs.get(job_id)
    assert job is not None
    assert job.status is JobStatus.FAILED
