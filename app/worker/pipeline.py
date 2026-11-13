"""Pipeline: runs the stages of one job in order.

queued -> extracting -> analyzing -> consolidating -> verifying -> done | failed

Each stage is idempotent: it skips work whose output is already stored, so re-running a
failed job resumes where it stopped.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.bootstrap import Deps
from app.domain.errors import ConsolidationError, FrameAnalysisError, MediaProcessingError
from app.domain.models import Consolidation, Frame, Job, JobStatus, LLMUsage
from app.domain.services import (
    build_report,
    count_unscaled_measurements,
    merge_image_metadata,
    merge_lines,
    strip_unscaled_measurements,
)

logger = logging.getLogger(__name__)

type Stage = Callable[[Deps, Job], Awaitable[None]]


async def ingest(deps: Deps, job: Job) -> None:
    """Read duration, resolution, capture time and GPS of the upload."""
    if job.metadata is not None:
        return
    paths = [deps.storage.local_path(k) for k in job.upload_keys]
    if job.media_kind == "video":
        metadata = await deps.metadata_reader.read(paths[0], "video")
    else:
        metadata = merge_image_metadata(
            [await deps.metadata_reader.read(p, "image") for p in paths]
        )
    await deps.jobs.save_metadata(job.id, metadata)


async def extract_frames(deps: Deps, job: Job) -> None:
    """Video -> selected keyframes; photos -> normalized frames. Stored as frames/<job>/fNNN.jpg."""
    if await deps.jobs.get_frames(job.id):
        return
    paths = [deps.storage.local_path(k) for k in job.upload_keys]
    if job.media_kind == "video":
        extracted = await deps.frame_extractor.from_video(paths[0], deps.settings.max_frames)
    else:
        extracted = await deps.frame_extractor.from_images(paths)
    if not extracted:
        raise MediaProcessingError("no usable frames")

    frames = []
    for i, ef in enumerate(extracted, start=1):
        frame_id = f"f{i:03d}"
        key = await deps.storage.put(f"frames/{job.id}/{frame_id}.jpg", ef.jpeg)
        frames.append(
            Frame(
                frame_id=frame_id,
                storage_key=key,
                timestamp_s=ef.timestamp_s,
                sharpness=ef.sharpness,
            )
        )
    await deps.jobs.save_frames(job.id, frames)


async def analyze_frames(deps: Deps, job: Job) -> None:
    """VisionModel.analyze per keyframe, at most `llm_concurrency` calls at a time.

    A frame that cannot be analyzed is marked failed and the job goes on; the stage fails
    only if no frame at all has an analysis. Frames analyzed in an earlier run are skipped,
    failed ones are tried again.
    """
    frames = await deps.jobs.get_frames(job.id)
    done = {a.frame_id for a in await deps.jobs.get_analyses(job.id)}
    todo = [f for f in frames if f.frame_id not in done]
    semaphore = asyncio.Semaphore(deps.settings.llm_concurrency)
    errors: dict[str, str] = {}

    async def analyze(frame: Frame) -> None:
        async with semaphore:
            image = await deps.storage.get(frame.storage_key)
            try:
                analysis, usage = await deps.vision_model.analyze(image, frame.frame_id)
            except FrameAnalysisError as e:
                await _record_usage(deps, job, frame.frame_id, e.usage)
                await deps.jobs.mark_frame_failed(job.id, frame.frame_id, str(e))
                errors[frame.frame_id] = str(e)
                logger.warning("job %s frame %s failed: %s", job.id, frame.frame_id, e)
                return
            await _record_usage(deps, job, frame.frame_id, usage)
            if stripped := count_unscaled_measurements(analysis):
                logger.info(
                    "job %s frame %s: dropped %d measurements without scale reference",
                    job.id, frame.frame_id, stripped,
                )  # fmt: skip
            await deps.jobs.save_analysis(job.id, strip_unscaled_measurements(analysis))

    # TaskGroup: an unexpected error (DB, storage) cancels the other calls and fails the stage
    # with that error (unwrapped, so the job's error message stays readable).
    try:
        async with asyncio.TaskGroup() as tg:
            for frame in todo:
                tg.create_task(analyze(frame))
    except* Exception as group:
        raise group.exceptions[0] from group

    if errors and len(errors) == len(frames):
        first = errors[min(errors)]
        raise FrameAnalysisError(
            f"no frame could be analyzed ({len(errors)} failed; first: {first})"
        )


async def _record_usage(deps: Deps, job: Job, frame_id: str, usage: list[LLMUsage]) -> None:
    for u in usage:
        await deps.jobs.record_llm_usage(job.id, "analyze_frames", u, frame_id=frame_id)


async def consolidate(deps: Deps, job: Job) -> None:
    """Agent merges per-frame findings into distinct lines; rule-based merge if the agent fails."""
    if await deps.jobs.get_report(job.id) is not None:
        return
    analyses = await deps.jobs.get_analyses(job.id)
    frames = {f.frame_id: f for f in await deps.jobs.get_frames(job.id)}

    async def load_image(frame_id: str) -> bytes:
        return await deps.storage.get(frames[frame_id].storage_key)

    extra_limitations: list[str] = []
    try:
        consolidation, usage = await deps.report_agent.consolidate(job.id, analyses, load_image)
    except ConsolidationError as e:
        logger.warning("job %s: consolidation agent failed (%s), using rule-based merge", job.id, e)
        usage = e.usage
        consolidation = Consolidation(lines=merge_lines(analyses), method="rules")
        extra_limitations.append(
            f"Automatic consolidation failed ({e}); lines were merged by simple rules "
            "(same type, material, color), so separate identical lines may be merged."
        )
    for u in usage:
        await deps.jobs.record_llm_usage(job.id, "consolidate", u)

    failed = len(frames) - len(analyses)
    if failed:
        extra_limitations.append(f"{failed} of {len(frames)} frames could not be analyzed.")
    report = build_report(job, consolidation, extra_limitations=extra_limitations)
    await deps.jobs.save_report(job.id, report)


async def verify(deps: Deps, job: Job) -> None:
    raise NotImplementedError


STAGES: tuple[tuple[str, JobStatus, Stage], ...] = (
    ("ingest", JobStatus.EXTRACTING, ingest),
    ("extract_frames", JobStatus.EXTRACTING, extract_frames),
    ("analyze_frames", JobStatus.ANALYZING, analyze_frames),
    ("consolidate", JobStatus.CONSOLIDATING, consolidate),
    ("verify", JobStatus.VERIFYING, verify),
)


async def run_pipeline(deps: Deps, job_id: UUID) -> None:
    """Run all stages. A failing stage marks the job `failed` with "<stage>: <reason>"."""
    job = await deps.jobs.get(job_id)
    if job is None:
        logger.warning("job %s not found, skipping", job_id)
        return
    if job.status is JobStatus.DONE:
        return

    for name, status, stage in STAGES:
        await deps.jobs.set_status(job_id, status)
        started = time.perf_counter()
        try:
            await stage(deps, job)
        except NotImplementedError:
            logger.info("job %s stopped at %s: not implemented yet", job_id, name)
            await deps.jobs.set_status(job_id, JobStatus.FAILED, f"{name}: not implemented yet")
            return
        except Exception as e:
            logger.exception("job %s failed at %s", job_id, name)
            await deps.jobs.set_status(job_id, JobStatus.FAILED, f"{name}: {e}")
            return
        await deps.jobs.record_stage_timing(job_id, name, round(time.perf_counter() - started, 3))
        job = await deps.jobs.get(job_id) or job  # later stages see what earlier ones stored

    await deps.jobs.set_status(job_id, JobStatus.DONE)
