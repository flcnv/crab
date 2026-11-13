"""Integration: enqueue into a real Redis and check the worker would pick it up."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from arq import create_pool
from arq.connections import RedisSettings
from arq.jobs import Job as ArqJob
from arq.jobs import JobStatus as ArqJobStatus

from app.adapters.queue.arq import PROCESS_JOB_TASK, ArqJobQueue
from app.settings import get_settings
from app.worker.main import WorkerSettings


@pytest.fixture
async def redis_settings() -> AsyncGenerator[RedisSettings]:
    s = get_settings()
    settings = RedisSettings(
        host=s.redis_host, port=s.redis_port, database=15, conn_retries=0, conn_timeout=1
    )
    try:
        pool = await create_pool(settings)
    except (OSError, ConnectionError) as e:
        pytest.skip(f"Redis not reachable: {e}")
    await pool.flushdb()
    yield settings
    await pool.flushdb()
    await pool.aclose()


def test_task_name_matches_worker() -> None:
    assert PROCESS_JOB_TASK in [f.__name__ for f in WorkerSettings.functions]


async def test_enqueue_is_queued_and_idempotent(redis_settings: RedisSettings) -> None:
    queue = ArqJobQueue(redis_settings)
    job_id = uuid.uuid4()
    try:
        await queue.enqueue(job_id)
        await queue.enqueue(job_id)  # same _job_id: no duplicate

        pool = await create_pool(redis_settings)
        arq_job = ArqJob(str(job_id), pool)
        assert await arq_job.status() is ArqJobStatus.queued
        info = await arq_job.info()
        assert info is not None
        assert info.function == PROCESS_JOB_TASK
        assert info.args == (str(job_id),)
        assert len(await pool.queued_jobs()) == 1
        await pool.aclose()
    finally:
        await queue.aclose()
