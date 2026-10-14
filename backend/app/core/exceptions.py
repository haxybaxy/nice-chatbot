"""Unified application error.

Use cases and dependencies raise ``AppError`` through its factories; the handlers in
``app.core.exception_handlers`` turn it into the JSON envelope::

    raise AppError.not_found("Organization", organization_id)
    raise AppError.conflict("Email already registered")
    raise AppError.forbidden("Only owners can grant the admin role")
    raise AppError.internal("Identity provider error", cause=exc)

``details`` is shown to the client in debug tiers; ``context`` is only logged.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Self


class ErrorCode(StrEnum):
    """Machine-readable cause on the JSON error envelope (``ErrorOut.code``)."""

    # The closed list of codes the backend can emit. It is typed on ``ErrorOut`` so the OpenAPI
    # document carries it as an enum and the frontend's generated types match it exactly —
    # adding a member is a wire change (``just openapi-snapshot``, then ``just contract-refresh``
    # in frontend/).
    BAD_REQUEST = "BAD_REQUEST"
    AUTH_FAILED = "AUTH_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


_DEFAULT_CODES: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    500: ErrorCode.INTERNAL_ERROR,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 500,
        code: ErrorCode | None = None,
        details: Mapping[str, object] | None = None,
        context: Mapping[str, object] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code: ErrorCode = code if code is not None else _DEFAULT_CODES.get(status_code, ErrorCode.INTERNAL_ERROR)
        self.details: dict[str, object] = dict(details) if details else {}
        self.context: dict[str, object] = dict(context) if context else {}
        self.cause = cause
        if cause is not None:
            self.__cause__ = cause

    # ── Factories ────────────────────────────────────────────────────────────

    @classmethod
    def not_found(cls, resource: str, identifier: object = None, **context: object) -> Self:
        message = f"{resource} not found" if identifier is None else f"{resource} '{identifier}' not found"
        return cls(message, status_code=404, code=ErrorCode.NOT_FOUND, context=context)

    @classmethod
    def auth_failed(cls, message: str = "Authentication failed", **context: object) -> Self:
        return cls(message, status_code=401, code=ErrorCode.AUTH_FAILED, context=context)

    @classmethod
    def forbidden(cls, message: str = "Access denied", **context: object) -> Self:
        return cls(message, status_code=403, code=ErrorCode.FORBIDDEN, context=context)

    @classmethod
    def conflict(cls, message: str, details: Mapping[str, object] | None = None, **context: object) -> Self:
        return cls(message, status_code=409, code=ErrorCode.CONFLICT, details=details, context=context)

    @classmethod
    def bad_request(cls, message: str, details: Mapping[str, object] | None = None, **context: object) -> Self:
        return cls(message, status_code=400, code=ErrorCode.BAD_REQUEST, details=details, context=context)

    @classmethod
    def internal(
        cls, message: str = "An internal error occurred", *, cause: Exception | None = None, **context: object
    ) -> Self:
        return cls(message, status_code=500, code=ErrorCode.INTERNAL_ERROR, cause=cause, context=context)

    @classmethod
    def service_unavailable(
        cls, message: str = "Service temporarily unavailable", *, cause: Exception | None = None, **context: object
    ) -> Self:
        return cls(message, status_code=503, code=ErrorCode.SERVICE_UNAVAILABLE, cause=cause, context=context)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message} (status={self.status_code})"
