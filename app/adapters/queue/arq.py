"""JobQueue on arq (Redis). The worker side lives in app/worker/main.py."""

from uuid import UUID

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

# Must match the function name registered in app.worker.main.WorkerSettings.functions.
PROCESS_JOB_TASK = "process_job"


class ArqJobQueue:
    def __init__(self, redis_settings: RedisSettings) -> None:
        self._redis_settings = redis_settings
        self._pool: ArqRedis | None = None

    async def _get_pool(self) -> ArqRedis:
        # Lazy: no Redis connection until the first enqueue.
        if self._pool is None:
            self._pool = await create_pool(self._redis_settings)
        return self._pool

    async def enqueue(self, job_id: UUID) -> None:
        pool = await self._get_pool()
        # _job_id makes enqueueing idempotent: the same job is never queued twice at once.
        await pool.enqueue_job(PROCESS_JOB_TASK, str(job_id), _job_id=str(job_id))

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
