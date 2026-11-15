"""Use cases: accept an upload and hand the new job to the worker; retry a failed job."""

import uuid
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import PurePath
from uuid import UUID

from app.domain.errors import (
    InvalidUploadError,
    JobNotFoundError,
    JobNotRetryableError,
    UploadTooLargeError,
)
from app.domain.models import Job, JobStatus, MediaKind
from app.domain.ports import JobQueue, JobRepository, Storage

MEDIA_KIND_BY_EXTENSION: frozendict[str, MediaKind] = frozendict(
    {
        ".mp4": "video",
        ".mov": "video",
        ".m4v": "video",
        ".webm": "video",
        ".jpg": "image",
        ".jpeg": "image",
        ".png": "image",
        ".webp": "image",
    }
)


@dataclass(frozen=True, slots=True)
class Upload:
    filename: str
    chunks: AsyncIterable[bytes]


def extension(filename: str) -> str:
    return PurePath(filename).suffix.lower()


def classify_uploads(filenames: Sequence[str], max_images: int) -> MediaKind:
    """Exactly one video, or 1..max_images photos. Never a mix."""
    if not filenames:
        raise InvalidUploadError("no files uploaded")

    kinds: list[MediaKind] = []
    for name in filenames:
        kind = MEDIA_KIND_BY_EXTENSION.get(extension(name))
        if kind is None:
            allowed = ", ".join(sorted(MEDIA_KIND_BY_EXTENSION))
            raise InvalidUploadError(f"unsupported file type: {name!r} (allowed: {allowed})")
        kinds.append(kind)

    if "video" in kinds:
        if len(kinds) > 1:
            raise InvalidUploadError(
                "upload either one video or photos, not both or several videos"
            )
        return "video"
    if len(kinds) > max_images:
        raise InvalidUploadError(f"too many photos: {len(kinds)} > {max_images}")
    return "image"


class _ByteBudget:
    """Shared size limit across all files of one upload."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.used = 0

    async def limit(self, chunks: AsyncIterable[bytes]) -> AsyncIterator[bytes]:
        async for chunk in chunks:
            self.used += len(chunk)
            if self.used > self.max_bytes:
                raise UploadTooLargeError(self.max_bytes)
            yield chunk


async def submit_job(
    uploads: Sequence[Upload],
    *,
    jobs: JobRepository,
    storage: Storage,
    queue: JobQueue,
    max_bytes: int,
    max_images: int,
) -> Job:
    kind = classify_uploads([u.filename for u in uploads], max_images)
    job_id = uuid.uuid7()  # time-ordered UUID (Python 3.14+)

    budget = _ByteBudget(max_bytes)
    keys: list[str] = []
    try:
        for i, upload in enumerate(uploads):
            key = f"uploads/{job_id}/{i:03d}{extension(upload.filename)}"
            await storage.put_stream(key, budget.limit(upload.chunks))
            keys.append(key)
    except BaseException:
        for key in keys:
            await storage.delete(key)
        raise

    job = await jobs.create(job_id, kind, keys)
    await _enqueue_or_fail(job_id, jobs, queue)
    return job


async def retry_job(job_id: UUID, *, jobs: JobRepository, queue: JobQueue) -> Job:
    """Re-run a `failed` job. Finished stages are skipped by the pipeline, `verify` reruns.

    Raises `JobNotFoundError` for an unknown job and `JobNotRetryableError` for any status
    other than `failed` (the status check and the switch to `queued` are one atomic step).
    """
    if not await jobs.requeue_failed(job_id):
        job = await jobs.get(job_id)
        raise JobNotRetryableError(job_id, job.status if job else "unknown")
    await _enqueue_or_fail(job_id, jobs, queue)
    job = await jobs.get(job_id)
    if job is None:  # deleted between the two calls
        raise JobNotFoundError(job_id)
    return job


async def _enqueue_or_fail(job_id: UUID, jobs: JobRepository, queue: JobQueue) -> None:
    """A job that cannot be handed to the worker is marked failed, so it can be retried."""
    try:
        await queue.enqueue(job_id)
    except Exception as e:
        await jobs.set_status(job_id, JobStatus.FAILED, error=f"could not enqueue job: {e}")
        raise
