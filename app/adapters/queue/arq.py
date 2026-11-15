from uuid import UUID

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

PROCESS_JOB_TASK = "process_job"


class ArqJobQueue:
    def __init__(self, redis_settings: RedisSettings) -> None:
        self._redis_settings = redis_settings
        self._pool: ArqRedis | None = None

    async def _get_pool(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(self._redis_settings)
        return self._pool

    async def enqueue(self, job_id: UUID) -> None:
        pool = await self._get_pool()
        await pool.enqueue_job(PROCESS_JOB_TASK, str(job_id), _job_id=str(job_id))

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
