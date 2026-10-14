"""OpenAPI helpers: declare the JSON error envelope on routes.

FastAPI would otherwise document its own ``HTTPValidationError`` for 422 and nothing for the
other statuses, while every error actually leaves through the envelope in
``app/core/exception_handlers.py``. ``tests/guards/test_openapi.py`` checks that each operation
documents the statuses it can produce and that every documented error uses :class:`ErrorOut`.
"""

from typing import cast

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
_JSON = "application/json"

type JsonObject = dict[str, object]


def error_responses(*status_codes: int) -> dict[int | str, dict[str, object]]:
    """``responses=`` entries for the given statuses, all typed as the error envelope.

    Every entry restates ``model`` on purpose: when the same status is declared at a more
    specific level (router → route) FastAPI replaces the whole per-status dict, so a bare
    ``{404: {"description": ...}}`` would silently drop the schema.
    """
    return {code: {"model": ErrorOut, "description": _DESCRIPTIONS[code]} for code in status_codes}


def _as_object(value: object) -> JsonObject | None:
    return cast(JsonObject, value) if isinstance(value, dict) else None


def _error_contents(spec: JsonObject) -> list[JsonObject]:
    """The ``content`` object of every documented 4xx/5xx response."""
    found: list[JsonObject] = []
    for item in (_as_object(spec.get("paths")) or {}).values():
        for operation in (_as_object(item) or {}).values():
            responses = _as_object((_as_object(operation) or {}).get("responses")) or {}
            for status, response in responses.items():
                content = _as_object((_as_object(response) or {}).get("content"))
                if status >= "400" and content is not None:
                    found.append(content)
    return found


def json_error_envelopes(spec: JsonObject) -> JsonObject:
    """Document every error response as ``application/json``, whatever the success media type.

    FastAPI files additional responses under the route's ``response_class.media_type``, so the
    event-stream operation would advertise the envelope as ``text/event-stream`` and the attachment
    download as ``application/octet-stream``. The exception handlers always answer with JSON; the
    document says so. In place and idempotent.
    """
    for content in _error_contents(spec):
        for media_type in [name for name in content if name != _JSON]:
            content[_JSON] = content.pop(media_type)
    return spec
