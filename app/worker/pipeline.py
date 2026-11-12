"""Pipeline stages. Each stage is idempotent and persists its output, so a failed job can resume.

queued -> extracting -> analyzing -> consolidating -> verifying -> done | failed
"""

from uuid import UUID


async def ingest(job_id: UUID) -> None:
    raise NotImplementedError


async def extract_frames(job_id: UUID) -> None:
    raise NotImplementedError


async def analyze_frames(job_id: UUID) -> None:
    """VisionModel.analyze per keyframe, concurrently under a semaphore."""
    raise NotImplementedError


async def consolidate(job_id: UUID) -> None:
    raise NotImplementedError


async def verify(job_id: UUID) -> None:
    raise NotImplementedError


async def render(job_id: UUID) -> None:
    raise NotImplementedError


async def run_pipeline(job_id: UUID) -> None:
    for stage in (ingest, extract_frames, analyze_frames, consolidate, verify, render):
        await stage(job_id)
