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
from app.domain.models import GeoPoint, JobStatus, TrenchReport
from tests.fakes import FakeJobQueue, InMemoryJobRepository


@pytest.fixture
def deps(tmp_path: Path) -> Deps:
    real = build_deps()
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
    for path in (
        f"/jobs/{job_id}",
        f"/jobs/{job_id}/report",
        f"/jobs/{job_id}/report.md",
        f"/jobs/{job_id}/report.geojson",
    ):
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
    deps.jobs.jobs[uuid.UUID(job_id)].status = JobStatus.DONE

    assert client.get(f"/jobs/{job_id}/report").json() == report.model_dump(mode="json")
    md = client.get(f"/jobs/{job_id}/report.md")
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/plain")
    assert md.text.startswith("# Trench documentation report")
    assert "No utility lines were identified." in md.text

    no_gps = client.get(f"/jobs/{job_id}/report.geojson")
    assert no_gps.status_code == 404
    assert no_gps.json()["detail"] == "report has no GPS location"

    deps.jobs.reports[uuid.UUID(job_id)] = report.model_copy(
        update={"location": GeoPoint(lat=47.3769, lon=8.5417)}
    )
    geo = client.get(f"/jobs/{job_id}/report.geojson")
    assert geo.status_code == 200
    assert geo.headers["content-type"] == "application/geo+json"
    assert geo.json()["features"][0]["geometry"]["coordinates"] == [8.5417, 47.3769]


REPORT_PATHS = ("report", "report.md", "report.geojson")


def _job_with_report(client: TestClient, deps: Deps, status: JobStatus, error: str | None) -> str:
    resp = client.post("/jobs", files=[("files", ("a.mp4", b"v", "video/mp4"))])
    job_id: str = resp.json()["job_id"]
    assert isinstance(deps.jobs, InMemoryJobRepository)
    deps.jobs.reports[uuid.UUID(job_id)] = TrenchReport(
        job_id=job_id,
        lines=[],
        verification_flags=[],
        limitations=[],
        location=GeoPoint(lat=47.0, lon=8.0),
    )
    job = deps.jobs.jobs[uuid.UUID(job_id)]
    job.status, job.error = status, error
    return job_id


@pytest.mark.parametrize("status", [JobStatus.CONSOLIDATING, JobStatus.VERIFYING])
def test_stored_but_unverified_report_is_not_served(
    client: TestClient, deps: Deps, status: JobStatus
) -> None:
    job_id = _job_with_report(client, deps, status, None)
    for path in REPORT_PATHS:
        resp = client.get(f"/jobs/{job_id}/{path}")
        assert resp.status_code == 409, path
        assert resp.json()["detail"] == f"report not ready, job status: {status}"


def test_report_of_failed_job_is_not_served(client: TestClient, deps: Deps) -> None:
    job_id = _job_with_report(client, deps, JobStatus.FAILED, "verify: storage lost")
    for path in REPORT_PATHS:
        resp = client.get(f"/jobs/{job_id}/{path}")
        assert resp.status_code == 409, path
        assert resp.json()["detail"] == "job failed (verify: storage lost); no verified report"


def test_report_of_done_job_is_served(client: TestClient, deps: Deps) -> None:
    job_id = _job_with_report(client, deps, JobStatus.DONE, None)
    for path in REPORT_PATHS:
        assert client.get(f"/jobs/{job_id}/{path}").status_code == 200, path


def test_retry_failed_job(client: TestClient, deps: Deps) -> None:
    job_id = _job_with_report(client, deps, JobStatus.FAILED, "verify: worker killed")

    resp = client.post(f"/jobs/{job_id}/retry")

    assert resp.status_code == 202
    body = resp.json()
    assert (body["job_id"], body["status"]) == (job_id, "queued")
    assert body["status_url"].endswith(f"/jobs/{job_id}")
    assert isinstance(deps.queue, FakeJobQueue)
    assert deps.queue.enqueued[-1] == uuid.UUID(job_id)
    assert client.get(f"/jobs/{job_id}").json()["error"] is None


def test_retry_of_job_that_did_not_fail_is_409(client: TestClient, deps: Deps) -> None:
    job_id = _job_with_report(client, deps, JobStatus.DONE, None)
    resp = client.post(f"/jobs/{job_id}/retry")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "job is done, only failed jobs can be retried"


def test_retry_of_unknown_job_is_404(client: TestClient) -> None:
    assert client.post(f"/jobs/{uuid.uuid4()}/retry").status_code == 404
