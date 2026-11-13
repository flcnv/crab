"""Domain errors. Adapters raise these; entrypoints map them (e.g. to HTTP 404)."""

from app.domain.errors.job import JobNotFoundError

__all__ = ["JobNotFoundError"]
