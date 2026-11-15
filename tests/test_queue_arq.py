import uuid
from collections.abc import AsyncGenerator

import pytest
from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from arq.jobs import Job as ArqJob
from arq.jobs import JobStatus as ArqJobStatus
from arq.worker import Worker, func
from redis.exceptions import RedisError

from app.adapters.queue.arq import PROCESS_JOB_TASK, ArqJobQueue
from app.settings import get_settings
from app.worker.main import WorkerSettings


async def _pool_or_skip(settings: RedisSettings) -> ArqRedis:
    try:
        return await create_pool(settings)
    except (OSError, ConnectionError, RedisError) as e:
        pytest.skip(f"Redis not reachable: {e}")


@pytest.fixture
async def redis_settings() -> AsyncGenerator[RedisSettings]:
    s = get_settings()
    settings = RedisSettings(
        host=s.redis_host, port=s.redis_port, database=15, conn_retries=0, conn_timeout=1
    )
    pool = await _pool_or_skip(settings)
    await pool.flushdb()
    yield settings
    await pool.flushdb()
    await pool.aclose()


async def test_unreachable_redis_skips_instead_of_erroring() -> None:
    nothing_there = RedisSettings(host="127.0.0.1", port=1, conn_retries=0, conn_timeout=1)
    with pytest.raises(pytest.skip.Exception, match="Redis not reachable"):
        await _pool_or_skip(nothing_there)


def test_worker_keeps_no_results() -> None:
    assert WorkerSettings.keep_result == 0


def test_task_name_matches_worker() -> None:
    assert PROCESS_JOB_TASK in [f.__name__ for f in WorkerSettings.functions]


async def test_enqueue_is_queued_and_idempotent(redis_settings: RedisSettings) -> None:
    queue = ArqJobQueue(redis_settings)
    job_id = uuid.uuid4()
    try:
        await queue.enqueue(job_id)
        await queue.enqueue(job_id)

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


async def test_finished_job_can_be_enqueued_again(redis_settings: RedisSettings) -> None:
    runs: list[str] = []

    async def process_job(ctx: dict[str, object], job_id: str) -> None:
        runs.append(job_id)

    def worker() -> Worker:
        return Worker(
            functions=[func(process_job, name=PROCESS_JOB_TASK)],
            redis_settings=redis_settings,
            burst=True,
            keep_result=WorkerSettings.keep_result,
            max_tries=WorkerSettings.max_tries,
        )

    queue = ArqJobQueue(redis_settings)
    job_id = uuid.uuid4()
    try:
        await queue.enqueue(job_id)
        await worker().main()
        await queue.enqueue(job_id)
        await worker().main()
    finally:
        await queue.aclose()

    assert runs == [str(job_id), str(job_id)]
