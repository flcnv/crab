from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import PlainTextResponse

from app.adapters.render.report import render_markdown
from app.api.deps import DepsDep
from app.api.schemas import JobCreated, JobOut
from app.domain.errors import JobNotFoundError
from app.domain.models import Job, TrenchReport
from app.domain.services import Upload, submit_job

router = APIRouter(prefix="/jobs", tags=["jobs"])

CHUNK_SIZE = 1024 * 1024


async def _read_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await file.read(CHUNK_SIZE):
        yield chunk


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: Request,
    files: Annotated[list[UploadFile], File(description="One video or several photos")],
    deps: DepsDep,
) -> JobCreated:
    """Store the upload, create a job and enqueue it for the worker."""
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


async def _get_job(deps: DepsDep, job_id: UUID) -> Job:
    job = await deps.jobs.get(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    return job


async def _get_report(deps: DepsDep, job_id: UUID) -> TrenchReport:
    job = await _get_job(deps, job_id)
    report = await deps.jobs.get_report(job_id)
    if report is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"report not ready, job status: {job.status}"
        )
    return report


@router.get("/{job_id}")
async def get_job(job_id: UUID, deps: DepsDep) -> JobOut:
    return JobOut.from_domain(await _get_job(deps, job_id))


@router.get("/{job_id}/report")
async def get_report(job_id: UUID, deps: DepsDep) -> TrenchReport:
    return await _get_report(deps, job_id)


@router.get("/{job_id}/report.md", response_class=PlainTextResponse)
async def get_report_markdown(job_id: UUID, deps: DepsDep) -> str:
    return render_markdown(await _get_report(deps, job_id))
