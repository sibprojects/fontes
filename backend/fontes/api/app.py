from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from fontes.api import health
from fontes.api.documents import router as documents_router
from fontes.api.limits import MULTIPART_OVERHEAD_BYTES, BodySizeLimit
from fontes.application.documents import (
    DocumentNotFoundError,
    DocumentService,
    EmptyFileError,
    FileTooLargeError,
)
from fontes.application.ports.health import HealthCheck
from fontes.domain.documents import DocumentError, InvalidUrlError, UnsupportedSourceError

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]

# Most specific first: the first matching class decides the status code.
_ERROR_STATUS: list[tuple[type[Exception], int]] = [
    (DocumentNotFoundError, status.HTTP_404_NOT_FOUND),
    (EmptyFileError, status.HTTP_400_BAD_REQUEST),
    (FileTooLargeError, status.HTTP_413_CONTENT_TOO_LARGE),
    (UnsupportedSourceError, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE),
    (InvalidUrlError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (DocumentError, status.HTTP_400_BAD_REQUEST),
]


async def _error_response(_: Request, exc: Exception) -> JSONResponse:
    code = next(code for cls, code in _ERROR_STATUS if isinstance(exc, cls))
    return JSONResponse({"detail": str(exc)}, status_code=code)


def create_app(
    checks: Sequence[HealthCheck],
    health_timeout: float,
    documents: DocumentService,
    max_upload_bytes: int,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="Fontes", lifespan=lifespan)
    app.state.health_checks = list(checks)
    app.state.health_timeout = health_timeout
    app.state.documents = documents
    app.state.max_upload_bytes = max_upload_bytes
    for exc_class in (DocumentNotFoundError, DocumentError):
        app.add_exception_handler(exc_class, _error_response)
    app.add_middleware(
        BodySizeLimit,
        path="/documents",
        max_bytes=max_upload_bytes + MULTIPART_OVERHEAD_BYTES,
    )
    app.include_router(health.router)
    app.include_router(documents_router)
    return app
