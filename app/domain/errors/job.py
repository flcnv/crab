from uuid import UUID


class JobNotFoundError(LookupError):
    def __init__(self, job_id: UUID) -> None:
        super().__init__(f"job {job_id} not found")
        self.job_id = job_id


class JobNotRetryableError(ValueError):
    def __init__(self, job_id: UUID, status: str) -> None:
        super().__init__(
            f"job is {status}; only failed jobs, or running jobs without progress "
            "for longer than the worker timeout, can be retried"
        )
        self.job_id = job_id
        self.status = status
