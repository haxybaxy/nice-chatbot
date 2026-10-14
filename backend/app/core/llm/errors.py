"""Translate model-provider failures into the one ``AppError`` the worker and the UI understand.

langchain-anthropic and langchain-openai re-raise their SDK errors as subclasses that also
inherit ``langchain_core.exceptions.Model*Error``, so the mapping is provider-neutral. The raw
``openai`` classes are matched as a fallback for the few paths (client construction, structured
output parsing) that bypass that translation; this is the only module allowed to import the SDK.

A refusal is not an exception: the agent graph reads ``stop_reason == "refusal"`` /
``finish_reason == "content_filter"`` off the response and turns it into a ``StopInfo``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import openai  # noqa: TID251
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

TOO_LONG = "Conversation is too long for this model; start a new conversation or pick a larger model"
MISCONFIGURED = "LLM provider misconfigured"
BUSY = "LLM provider is busy, please retry"
UNAVAILABLE = "LLM provider temporarily unavailable"
NOT_SERVED = "Model not served by the provider"
REJECTED = "LLM provider rejected the request"
STEP_LIMIT = "The assistant hit its step limit"
TOOK_TOO_LONG = "The assistant took too long to answer"
_CONTEXT_LENGTH_MARKERS = (
    "context_length",
    "context length",
    "maximum context",
    "too many tokens",
    "prompt is too long",
)


def _retry_after(error: BaseException) -> int | None:
    """``Retry-After`` seconds from the SDK error's HTTP response, when present."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return None
    value = cast("Mapping[str, object]", headers).get("retry-after")
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _busy(error: BaseException) -> AppError:
    retry_after = _retry_after(error)
    context: dict[str, object] = {}
    if retry_after is not None:
        context["retry_after_s"] = retry_after
    return AppError.service_unavailable(BUSY, cause=error if isinstance(error, Exception) else None, **context)


def _from_langchain(error: BaseException) -> AppError | None:
    cause = error if isinstance(error, Exception) else None
    if isinstance(error, ContextOverflowError):
        return AppError.bad_request(TOO_LONG)
    if isinstance(error, ModelAuthenticationError | ModelPermissionDeniedError):
        return AppError.internal(MISCONFIGURED, cause=cause)
    if isinstance(error, ModelRateLimitError):
        return _busy(error)
    if isinstance(error, ModelNotFoundError):
        return AppError.internal(NOT_SERVED, cause=cause)
    if isinstance(error, ModelInvalidRequestError):
        return AppError.internal(REJECTED, cause=cause)
    if isinstance(error, ModelTimeoutError | ModelConnectionError | ModelAPIError):
        return AppError.service_unavailable(UNAVAILABLE, cause=cause)
    return None


def _from_openai(error: BaseException) -> AppError | None:
    cause = error if isinstance(error, Exception) else None
    if isinstance(error, openai.AuthenticationError | openai.PermissionDeniedError):
        return AppError.internal(MISCONFIGURED, cause=cause)
    if isinstance(error, openai.RateLimitError):
        return _busy(error)
    if isinstance(error, openai.NotFoundError):
        return AppError.internal(NOT_SERVED, cause=cause)
    if isinstance(error, openai.BadRequestError):
        message = str(error).lower()
        if any(marker in message for marker in _CONTEXT_LENGTH_MARKERS):
            return AppError.bad_request(TOO_LONG)
        return AppError.internal(REJECTED, cause=cause)
    if isinstance(error, openai.APITimeoutError | openai.APIConnectionError):
        return AppError.service_unavailable(UNAVAILABLE, cause=cause)
    if isinstance(error, openai.APIStatusError):
        if error.status_code >= 500:
            return AppError.service_unavailable(UNAVAILABLE, cause=cause)
        return AppError.internal(REJECTED, cause=cause, status_code=error.status_code)
    return None


def to_app_error(error: BaseException) -> AppError | None:
    """The ``AppError`` for a failure raised by a model call or the graph, or ``None`` when it is not one.

    The message is safe to show the user (``errorText`` / ``run.error``); the original exception
    rides along as ``cause`` for the logs.
    """
    if isinstance(error, AppError):
        return error
    translated = _from_langchain(error) or _from_openai(error)
    if translated is not None:
        return translated
    if isinstance(error, GraphRecursionError):
        return AppError.internal(STEP_LIMIT, cause=error)
    if isinstance(error, TimeoutError):
        return AppError.service_unavailable(TOOK_TOO_LONG, cause=error)
    return None
