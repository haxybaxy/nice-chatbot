"""Request-scoped context: correlation id and authenticated user id.

Held in ``ContextVar``s so the logging processor, the middleware and the auth dependency all
read/write the same values without passing them around. Deliberately dependency-free.
"""

import uuid
from contextvars import ContextVar

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
request_user_id: ContextVar[str | None] = ContextVar("request_user_id", default=None)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def set_correlation_id(value: str) -> None:
    correlation_id.set(value)


def get_correlation_id() -> str | None:
    return correlation_id.get()


def bind_user_id(user_id: str) -> None:
    """Attach the authenticated user's id to every subsequent log line of this request."""
    request_user_id.set(user_id)
