from typing import Protocol
from uuid import UUID


class JobQueue(Protocol):
    async def enqueue(self, job_id: UUID) -> None: ...
    async def aclose(self) -> None: ...
