from uuid import UUID

from fastapi import APIRouter, UploadFile
from fastapi.responses import PlainTextResponse

from app.api.schemas import JobCreated, JobOut
from app.domain.models import TrenchReport

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=202)
async def create_job(files: list[UploadFile]) -> JobCreated:
    """Store upload(s), create job row, enqueue `process_job` in arq."""
    raise NotImplementedError


@router.get("/{job_id}")
async def get_job(job_id: UUID) -> JobOut:
    raise NotImplementedError


@router.get("/{job_id}/report")
async def get_report(job_id: UUID) -> TrenchReport:
    raise NotImplementedError


@router.get("/{job_id}/report.md", response_class=PlainTextResponse)
async def get_report_markdown(job_id: UUID) -> str:
    raise NotImplementedError
