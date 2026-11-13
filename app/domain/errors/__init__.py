"""Domain errors. Adapters raise these; entrypoints map them (e.g. to HTTP 404)."""

from app.domain.errors.analysis import ConsolidationError, FrameAnalysisError, ModelCallError
from app.domain.errors.job import JobNotFoundError
from app.domain.errors.media import MediaProcessingError
from app.domain.errors.upload import InvalidUploadError, UploadTooLargeError

__all__ = [
    "ConsolidationError",
    "FrameAnalysisError",
    "InvalidUploadError",
    "JobNotFoundError",
    "MediaProcessingError",
    "ModelCallError",
    "UploadTooLargeError",
]
