from uuid import UUID


class JobNotFoundError(LookupError):
    def __init__(self, job_id: UUID) -> None:
        super().__init__(f"job {job_id} not found")
        self.job_id = job_id


class JobNotRetryableError(ValueError):
    """Only `failed` jobs can be retried."""

    def __init__(self, job_id: UUID, status: str) -> None:
        super().__init__(f"job is {status}, only failed jobs can be retried")
        self.job_id = job_id
        self.status = status
