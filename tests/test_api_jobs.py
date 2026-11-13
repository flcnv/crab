import dataclasses
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.storage.local import LocalStorage
from app.api.deps import get_deps
from app.api.main import app
from app.bootstrap import Deps, build_deps
from app.domain.models import TrenchReport
from tests.fakes import FakeJobQueue, InMemoryJobRepository


@pytest.fixture
def deps(tmp_path: Path) -> Deps:
    real = build_deps()  # engine/queue are lazy: nothing connects
    settings = real.settings.model_copy(update={"max_upload_bytes": 1024, "max_images_per_job": 3})
    return dataclasses.replace(
        real,
        settings=settings,
        jobs=InMemoryJobRepository(),
        queue=FakeJobQueue(),
        storage=LocalStorage(tmp_path),
    )


@pytest.fixture
def client(deps: Deps) -> Iterator[TestClient]:
    app.dependency_overrides[get_deps] = lambda: deps
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_create_job_with_video(client: TestClient, deps: Deps) -> None:
    resp = client.post("/jobs", files=[("files", ("trench.mp4", b"fake video", "video/mp4"))])

    assert resp.status_code == 202, resp.text
    body = resp.json()
    job_id = uuid.UUID(body["job_id"])
    assert body["status"] == "queued"
    assert body["status_url"].endswith(f"/jobs/{job_id}")
    assert isinstance(deps.queue, FakeJobQueue)
    assert deps.queue.enqueued == [job_id]


def test_create_job_with_photos_then_get(client: TestClient) -> None:
    files = [("files", (f"p{i}.jpg", b"img", "image/jpeg")) for i in range(3)]
    job_id = client.post("/jobs", files=files).json()["job_id"]

    resp = client.get(f"/jobs/{job_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["media_kind"] == "image"
    assert body["file_count"] == 3
    assert body["cost_usd"] == 0.0


@pytest.mark.parametrize(
    ("files", "status_code"),
    [
        ([("files", ("notes.txt", b"x", "text/plain"))], 422),
        ([("files", ("a.mp4", b"x", "video/mp4")), ("files", ("b.jpg", b"x", "image/jpeg"))], 422),
        ([("files", (f"{i}.jpg", b"x", "image/jpeg")) for i in range(4)], 422),
        ([("files", ("big.mp4", b"x" * 2048, "video/mp4"))], 413),
    ],
)
def test_create_job_rejects(
    client: TestClient, files: list[tuple[str, tuple[str, bytes, str]]], status_code: int
) -> None:
    resp = client.post("/jobs", files=files)
    assert resp.status_code == status_code, resp.text
    assert resp.json()["detail"]


def test_create_job_without_files(client: TestClient) -> None:
    assert client.post("/jobs").status_code == 422


def test_unknown_job_is_404(client: TestClient) -> None:
    job_id = uuid.uuid4()
    for path in (f"/jobs/{job_id}", f"/jobs/{job_id}/report", f"/jobs/{job_id}/report.md"):
        assert client.get(path).status_code == 404, path


def test_report_not_ready_then_ready(client: TestClient, deps: Deps) -> None:
    job_id = client.post("/jobs", files=[("files", ("a.mp4", b"v", "video/mp4"))]).json()["job_id"]

    not_ready = client.get(f"/jobs/{job_id}/report")
    assert not_ready.status_code == 409
    assert "queued" in not_ready.json()["detail"]

    report = TrenchReport(
        job_id=job_id, lines=[], verification_flags=[], limitations=[], location=None
    )
    assert isinstance(deps.jobs, InMemoryJobRepository)
    deps.jobs.reports[uuid.UUID(job_id)] = report

    assert client.get(f"/jobs/{job_id}/report").json() == report.model_dump(mode="json")
    assert client.get(f"/jobs/{job_id}/report.md").status_code == 501  # rendering: Day 2
