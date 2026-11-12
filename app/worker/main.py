"""arq worker settings. Run: `uv run arq app.worker.main.WorkerSettings`."""

from typing import Any, ClassVar
from uuid import UUID

from arq.connections import RedisSettings

from app.settings import get_settings
from app.worker.pipeline import run_pipeline


async def process_job(ctx: dict[str, Any], job_id: str) -> None:
    await run_pipeline(UUID(job_id))


class WorkerSettings:
    functions: ClassVar = [process_job]
    redis_settings: ClassVar = RedisSettings.from_dsn(get_settings().redis_url)
