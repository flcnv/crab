"""Pipeline: runs the stages of one job in order.

queued -> extracting -> analyzing -> consolidating -> verifying -> done | failed

Each stage is idempotent: it skips work whose output is already stored, so re-running a
failed job resumes where it stopped.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.bootstrap import Deps
from app.domain.errors import MediaProcessingError
from app.domain.models import Frame, Job, JobStatus
from app.domain.services import merge_image_metadata

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
    """VisionModel.analyze per keyframe, concurrently under a semaphore."""
    raise NotImplementedError


async def consolidate(deps: Deps, job: Job) -> None:
    raise NotImplementedError


async def verify(deps: Deps, job: Job) -> None:
    raise NotImplementedError


async def render(deps: Deps, job: Job) -> None:
    raise NotImplementedError


STAGES: tuple[tuple[str, JobStatus, Stage], ...] = (
    ("ingest", JobStatus.EXTRACTING, ingest),
    ("extract_frames", JobStatus.EXTRACTING, extract_frames),
    ("analyze_frames", JobStatus.ANALYZING, analyze_frames),
    ("consolidate", JobStatus.CONSOLIDATING, consolidate),
    ("verify", JobStatus.VERIFYING, verify),
    ("render", JobStatus.VERIFYING, render),
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
