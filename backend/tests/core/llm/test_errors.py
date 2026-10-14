"""Provider failures → the one ``AppError`` with a user-safe message."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from langchain_core.exceptions import (
    ContextOverflowError,
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelInvalidRequestError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from langgraph.errors import GraphRecursionError

from app.core.exceptions import AppError
from app.core.llm.errors import (
    BUSY,
    MISCONFIGURED,
    NOT_SERVED,
    REJECTED,
    STEP_LIMIT,
    TOO_LONG,
    TOOK_TOO_LONG,
    UNAVAILABLE,
    to_app_error,
)


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (ContextOverflowError("too long"), 400, TOO_LONG),
        (ModelAuthenticationError("bad key"), 500, MISCONFIGURED),
        (ModelPermissionDeniedError("no"), 500, MISCONFIGURED),
        (ModelRateLimitError("slow down"), 503, BUSY),
        (ModelNotFoundError("nope"), 500, NOT_SERVED),
        (ModelInvalidRequestError("bad"), 500, REJECTED),
        (ModelTimeoutError("t"), 503, UNAVAILABLE),
        (ModelConnectionError("c"), 503, UNAVAILABLE),
        (ModelAPIError("500"), 503, UNAVAILABLE),
        (GraphRecursionError("limit"), 500, STEP_LIMIT),
        (TimeoutError(), 503, TOOK_TOO_LONG),
    ],
)
def test_translations(error: Exception, status: int, message: str) -> None:
    translated = to_app_error(error)
    assert translated is not None
    assert (translated.status_code, translated.message) == (status, message)
    if not isinstance(error, ContextOverflowError):
        assert translated.cause is error


@dataclass
class _Response:
    headers: dict[str, str]


class _RateLimitedError(ModelRateLimitError):
    def __init__(self) -> None:
        super().__init__("429")
        self.response = _Response(headers={"retry-after": "7"})


def test_retry_after_is_kept_as_context() -> None:
    translated = to_app_error(_RateLimitedError())
    assert translated is not None
    assert translated.context == {"retry_after_s": 7}


def test_passthrough_and_unknown() -> None:
    original = AppError.conflict("fenced")
    assert to_app_error(original) is original
    assert to_app_error(ValueError("not a provider error")) is None
    assert to_app_error(KeyError("x")) is None
