from uuid import UUID


class JobNotFoundError(LookupError):
    def __init__(self, job_id: UUID) -> None:
        super().__init__(f"job {job_id} not found")
        self.job_id = job_id
