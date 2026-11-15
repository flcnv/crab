"""Map domain errors to HTTP responses, so routes stay free of try/except."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.domain.errors import (
    InvalidUploadError,
    JobNotFoundError,
    JobNotRetryableError,
    UploadTooLargeError,
)

_STATUS_BY_ERROR: frozendict[type[Exception], int] = frozendict(
    {
        JobNotFoundError: status.HTTP_404_NOT_FOUND,
        JobNotRetryableError: status.HTTP_409_CONFLICT,
        InvalidUploadError: status.HTTP_422_UNPROCESSABLE_CONTENT,
        UploadTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
        NotImplementedError: status.HTTP_501_NOT_IMPLEMENTED,
    }
)


def register_error_handlers(app: FastAPI) -> None:
    for error_type, status_code in _STATUS_BY_ERROR.items():

        async def handler(
            _: Request, exc: Exception, status_code: int = status_code
        ) -> JSONResponse:
            return JSONResponse(status_code=status_code, content={"detail": str(exc) or None})

        app.add_exception_handler(error_type, handler)
