from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.adapters.storage.local import LocalStorage
from app.domain.errors import InvalidUploadError, UploadTooLargeError
from app.domain.models import JobStatus
from app.domain.services import Upload, classify_uploads, submit_job
from tests.fakes import FakeJobQueue, InMemoryJobRepository


def _stored_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


async def _chunks(data: bytes, size: int = 4) -> AsyncIterator[bytes]:
    for i in range(0, len(data), size):
        yield data[i : i + size]


@pytest.mark.parametrize(
    ("names", "kind"),
    [(["a.MP4"], "video"), (["a.jpg", "b.PNG", "c.webp"], "image")],
)
def test_classify_ok(names: list[str], kind: str) -> None:
    assert classify_uploads(names, max_images=5) == kind


@pytest.mark.parametrize(
    "names",
    [[], ["a.txt"], ["a.mp4", "b.jpg"], ["a.mp4", "b.mov"], ["noext"], ["1.jpg"] * 6],
)
def test_classify_rejects(names: list[str]) -> None:
    with pytest.raises(InvalidUploadError):
        classify_uploads(names, max_images=5)


async def test_submit_stores_creates_and_enqueues(tmp_path: Path) -> None:
    jobs, queue, storage = InMemoryJobRepository(), FakeJobQueue(), LocalStorage(tmp_path)

    job = await submit_job(
        [Upload("one.jpg", _chunks(b"first")), Upload("../../two.png", _chunks(b"second"))],
        jobs=jobs,
        storage=storage,
        queue=queue,
        max_bytes=100,
        max_images=5,
    )

    assert job.status is JobStatus.QUEUED
    assert job.media_kind == "image"
    assert job.upload_keys == [f"uploads/{job.id}/000.jpg", f"uploads/{job.id}/001.png"]
    assert await storage.get(job.upload_keys[1]) == b"second"
    assert queue.enqueued == [job.id]


async def test_submit_over_limit_cleans_up(tmp_path: Path) -> None:
    jobs, storage = InMemoryJobRepository(), LocalStorage(tmp_path)

    with pytest.raises(UploadTooLargeError):
        await submit_job(
            [Upload("a.jpg", _chunks(b"x" * 8)), Upload("b.jpg", _chunks(b"y" * 8))],
            jobs=jobs,
            storage=storage,
            queue=FakeJobQueue(),
            max_bytes=10,
            max_images=5,
        )

    assert jobs.jobs == {}
    assert _stored_files(tmp_path) == []


async def test_submit_marks_job_failed_when_enqueue_fails(tmp_path: Path) -> None:
    jobs = InMemoryJobRepository()

    with pytest.raises(ConnectionError):
        await submit_job(
            [Upload("a.mp4", _chunks(b"video"))],
            jobs=jobs,
            storage=LocalStorage(tmp_path),
            queue=FakeJobQueue(fail=True),
            max_bytes=100,
            max_images=5,
        )

    [job] = jobs.jobs.values()
    assert job.status is JobStatus.FAILED
    assert job.error is not None
    assert "enqueue" in job.error


async def test_local_storage_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        await LocalStorage(tmp_path).put("../outside.txt", b"x")
