from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, PlainTextResponse

from app.adapters.render.report import render_geojson, render_markdown
from app.api.deps import DepsDep
from app.api.schemas.jobs import JobCreated, JobOut
from app.domain.errors import JobNotFoundError
from app.domain.models import Job, JobStatus, TrenchReport
from app.domain.services import Upload, retry_job, submit_job

router = APIRouter(prefix="/jobs", tags=["jobs"])

CHUNK_SIZE = 1024 * 1024
GEOJSON = "application/geo+json"


async def _read_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await file.read(CHUNK_SIZE):
        yield chunk


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: Request,
    files: Annotated[list[UploadFile], File(description="One video or several photos")],
    deps: DepsDep,
) -> JobCreated:
    job = await submit_job(
        [Upload(filename=f.filename or "", chunks=_read_chunks(f)) for f in files],
        jobs=deps.jobs,
        storage=deps.storage,
        queue=deps.queue,
        max_bytes=deps.settings.max_upload_bytes,
        max_images=deps.settings.max_images_per_job,
    )
    return JobCreated(
        job_id=job.id,
        status=job.status,
        status_url=str(request.url_for("get_job", job_id=job.id)),
    )


@router.post("/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry(job_id: UUID, request: Request, deps: DepsDep) -> JobCreated:
    job = await retry_job(
        job_id,
        jobs=deps.jobs,
        queue=deps.queue,
        stale_after=timedelta(seconds=deps.settings.job_timeout_s),
    )
    return JobCreated(
        job_id=job.id,
        status=job.status,
        status_url=str(request.url_for("get_job", job_id=job.id)),
    )


async def _get_job(deps: DepsDep, job_id: UUID) -> Job:
    job = await deps.jobs.get(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    return job


async def _get_report(deps: DepsDep, job_id: UUID) -> tuple[Job, TrenchReport]:
    job = await _get_job(deps, job_id)
    if job.status is JobStatus.FAILED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"job failed ({job.error}); no verified report"
        )
    report = await deps.jobs.get_report(job_id) if job.status is JobStatus.DONE else None
    if report is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"report not ready, job status: {job.status}"
        )
    return job, report


@router.get("/{job_id}")
async def get_job(job_id: UUID, deps: DepsDep) -> JobOut:
    return JobOut.from_domain(await _get_job(deps, job_id))


@router.get("/{job_id}/report")
async def get_report(job_id: UUID, deps: DepsDep) -> TrenchReport:
    _, report = await _get_report(deps, job_id)
    return report


@router.get("/{job_id}/report.md", response_class=PlainTextResponse)
async def get_report_markdown(job_id: UUID, deps: DepsDep) -> str:
    job, report = await _get_report(deps, job_id)
    return render_markdown(report, job)


@router.get(
    "/{job_id}/report.geojson",
    response_class=JSONResponse,
    responses={200: {"content": {GEOJSON: {}}}, 404: {"description": "No GPS location"}},
)
async def get_report_geojson(job_id: UUID, deps: DepsDep) -> JSONResponse:
    _, report = await _get_report(deps, job_id)
    geojson = render_geojson(report)
    if geojson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="report has no GPS location")
    return JSONResponse(geojson, media_type=GEOJSON)
