"""FastAPI exception handlers producing one JSON error envelope.

Wire contract is :class:`app.core.schemas.ErrorOut`, camelCase through the alias generator::

    {"error": str, "code": ErrorCode, "statusCode": int, "correlationId": str, "details"?: object}

``details`` is included only in debug tiers (``settings.expose_debug_details``). The log fields
in the same functions (``error_code``, ``status_code``, …) are structlog attributes, never sent to
a client, and stay snake_case. Routes declare these responses with
``app.core.openapi.error_responses``.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import cast

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse  # noqa: TID251
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException  # noqa: TID251
from starlette.types import ExceptionHandler

from app.core.config import settings
from app.core.context import get_correlation_id
from app.core.exceptions import AppError, ErrorCode
from app.core.logging_config import get_logger
from app.core.schemas import ErrorOut

logger = get_logger(__name__)


def _envelope(
    *,
    status_code: int,
    error: str,
    code: ErrorCode,
    details: object = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorOut(
        error=error,
        code=code,
        status_code=status_code,
        correlation_id=get_correlation_id() or "unknown",
        details=details if details is not None and settings.expose_debug_details else None,
    )
    merged_headers = dict(headers or {})
    if status_code == 401:
        merged_headers.setdefault("WWW-Authenticate", "Bearer")
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True, exclude_none=True),
        headers=merged_headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    log_data: dict[str, object] = {
        "error_code": exc.code,
        "status_code": exc.status_code,
        "error": exc.message,
        "path": request.url.path,
        "method": request.method,
        **exc.context,
    }
    if exc.status_code >= 500:
        logger.error("server error", exc_info=exc.cause or exc, **log_data)
    else:
        logger.warning("client error", **log_data)
    return _envelope(status_code=exc.status_code, error=exc.message, code=exc.code, details=exc.details or None)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic embeds the original exception object in each error's `ctx`, which isn't
    # JSON-serializable; coerce the whole structure, stringifying embedded exceptions.
    errors: object = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
    logger.warning("request validation failed", path=request.url.path, method=request.method, errors=errors)
    return _envelope(status_code=422, error="Validation error", code=ErrorCode.VALIDATION_ERROR, details=errors)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    logger.warning(
        "http exception", status_code=exc.status_code, detail=exc.detail, path=request.url.path, method=request.method
    )
    return _envelope(status_code=exc.status_code, error=str(exc.detail), code=ErrorCode.HTTP_ERROR, headers=exc.headers)


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    logger.warning(
        "database integrity error",
        orig_type=type(exc.orig).__name__ if exc.orig else None,
        path=request.url.path,
        method=request.method,
    )
    return _envelope(status_code=409, error="Resource conflict", code=ErrorCode.CONFLICT)


async def operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    # One short line per failed request, no stack trace: when the database is down every
    # request lands here and a traceback per poll adds nothing.
    logger.warning(
        "database unavailable",
        db_error=type(exc.orig).__name__ if exc.orig else type(exc).__name__,
        path=request.url.path,
        method=request.method,
    )
    return _envelope(status_code=503, error="Database temporarily unavailable", code=ErrorCode.SERVICE_UNAVAILABLE)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled exception",
        exception_type=type(exc).__name__,
        path=request.url.path,
        method=request.method,
        exc_info=exc,
    )
    return _envelope(status_code=500, error="Internal server error", code=ErrorCode.INTERNAL_ERROR, details=str(exc))


def _register[E: Exception](
    app: FastAPI, exc_type: type[E], handler: Callable[[Request, E], Awaitable[Response]]
) -> None:
    # Starlette types every handler as (Request, Exception); ours are narrower on the exception,
    # which is exactly the type add_exception_handler dispatches on. One cast here instead of
    # one ignore per registration.
    app.add_exception_handler(exc_type, cast(ExceptionHandler, handler))


def register_exception_handlers(app: FastAPI) -> None:
    _register(app, AppError, app_error_handler)
    _register(app, RequestValidationError, validation_error_handler)
    # Starlette's HTTPException — FastAPI's subclasses it, so this covers both, and it is the
    # only way to envelope the 404/405 the router raises for an unmatched path.
    _register(app, HTTPException, http_exception_handler)
    _register(app, IntegrityError, integrity_error_handler)
    _register(app, OperationalError, operational_error_handler)
    _register(app, Exception, unhandled_exception_handler)
