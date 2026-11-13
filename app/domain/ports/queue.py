from typing import Protocol
from uuid import UUID


class JobQueue(Protocol):
    """Hands a job over to the background worker."""

    async def enqueue(self, job_id: UUID) -> None: ...
    async def aclose(self) -> None: ...
