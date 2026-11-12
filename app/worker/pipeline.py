"""Pipeline stages. Each stage is idempotent and persists its output, so a failed job can resume.

queued -> extracting -> analyzing -> consolidating -> verifying -> done | failed
"""

from uuid import UUID

from app.bootstrap import Deps


async def ingest(deps: Deps, job_id: UUID) -> None:
    raise NotImplementedError


async def extract_frames(deps: Deps, job_id: UUID) -> None:
    raise NotImplementedError


async def analyze_frames(deps: Deps, job_id: UUID) -> None:
    """VisionModel.analyze per keyframe, concurrently under a semaphore."""
    raise NotImplementedError


async def consolidate(deps: Deps, job_id: UUID) -> None:
    raise NotImplementedError


async def verify(deps: Deps, job_id: UUID) -> None:
    raise NotImplementedError


async def render(deps: Deps, job_id: UUID) -> None:
    raise NotImplementedError


async def run_pipeline(deps: Deps, job_id: UUID) -> None:
    for stage in (ingest, extract_frames, analyze_frames, consolidate, verify, render):
        await stage(deps, job_id)
