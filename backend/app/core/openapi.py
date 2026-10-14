"""OpenAPI helpers: declare the JSON error envelope on routes.

FastAPI would otherwise document its own ``HTTPValidationError`` for 422 and nothing for the
other statuses, while every error actually leaves through the envelope in
``app/core/exception_handlers.py``. ``tests/guards/test_openapi.py`` checks that each operation
documents the statuses it can produce and that every documented error uses :class:`ErrorOut`.
"""

from app.core.schemas import ErrorOut

_DESCRIPTIONS: dict[int, str] = {
    400: "Bad request",
    401: "Missing, invalid or expired bearer token",
    403: "Insufficient role",
    404: "Not found, or not visible to the caller",
    409: "Conflicts with existing state",
    422: "Request validation failed",
    500: "Internal server error",
    503: "A dependency (database, identity provider) is unavailable",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, object]]:
    """``responses=`` entries for the given statuses, all typed as the error envelope.

    Every entry restates ``model`` on purpose: when the same status is declared at a more
    specific level (router → route) FastAPI replaces the whole per-status dict, so a bare
    ``{404: {"description": ...}}`` would silently drop the schema.
    """
    return {code: {"model": ErrorOut, "description": _DESCRIPTIONS[code]} for code in status_codes}
