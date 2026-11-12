"""arq worker settings. Run: `uv run arq app.worker.main.WorkerSettings`."""

from typing import Any, ClassVar
from uuid import UUID

from arq.connections import RedisSettings

from app.bootstrap import build_deps
from app.settings import get_settings
from app.worker.pipeline import run_pipeline


async def startup(ctx: dict[str, Any]) -> None:
    ctx["deps"] = build_deps()


async def process_job(ctx: dict[str, Any], job_id: str) -> None:
    await run_pipeline(ctx["deps"], UUID(job_id))


class WorkerSettings:
    functions: ClassVar = [process_job]
    on_startup = startup
    redis_settings: ClassVar = RedisSettings.from_dsn(get_settings().redis_url)
