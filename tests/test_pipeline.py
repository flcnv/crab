import dataclasses
import uuid
from pathlib import Path
from uuid import UUID

import pytest

from app.adapters.storage.local import LocalStorage
from app.bootstrap import Deps, build_deps
from app.domain.errors import MediaProcessingError
from app.domain.models import ExtractedFrame, GeoPoint, JobStatus, MediaKind, MediaMetadata
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


@pytest.fixture
def deps(tmp_path: Path) -> Deps:
    return dataclasses.replace(
        build_deps(),
        jobs=InMemoryJobRepository(),
        queue=FakeJobQueue(),
        storage=LocalStorage(tmp_path),
        metadata_reader=FakeMetadataReader(),
        frame_extractor=FakeFrameExtractor(),
    )


async def _new_job(deps: Deps, kind: MediaKind, *names: str) -> UUID:
    keys = [await deps.storage.put(f"uploads/{n}", b"data-" + n.encode()) for n in names]
    return (await deps.jobs.create(uuid.uuid4(), kind, keys)).id


async def test_video_job_stores_frames_and_stops_at_analyze(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")

    await run_pipeline(deps, job_id)

    job = await deps.jobs.get(job_id)
    assert job is not None
    assert job.status is JobStatus.FAILED
    assert job.error == "analyze_frames: not implemented yet"
    assert job.metadata is not None
    assert job.metadata.location == GeoPoint(lat=1, lon=2)
    assert set(job.stage_timings_s) == {"ingest", "extract_frames"}

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


async def test_rerun_skips_finished_stages(deps: Deps) -> None:
    job_id = await _new_job(deps, "video", "clip.mp4")
    await run_pipeline(deps, job_id)
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
    await run_pipeline(deps, uuid.uuid4())  # no exception
