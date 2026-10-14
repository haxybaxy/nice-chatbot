"""Shared Pydantic bases for the HTTP boundary.

Every request (``*In``) and response (``*Out``) schema inherits these instead of
``pydantic.BaseModel`` (ruff ``TID251`` bans the direct import). Contract: snake_case fields in
Python, camelCase on the wire. Inputs accept either spelling and have surrounding whitespace
stripped from strings (opt out per field with :data:`VerbatimStr`); outputs emit camelCase via
FastAPI's default ``response_model_by_alias=True``. ``.model_dump()`` stays snake_case for
internal use.

Datetime fields on the boundary are typed :data:`UtcDatetime`, never bare ``datetime``: it
serializes to UTC ISO-8601 with a ``Z`` suffix *and* keeps the field's JSON Schema type intact.
"""

from datetime import UTC, datetime
from typing import Annotated, ClassVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    PlainSerializer,
    StringConstraints,
    WithJsonSchema,
)
from pydantic.alias_generators import to_camel

from app.core.exceptions import ErrorCode


def _to_utc_z(value: datetime) -> str:
    """Normalize to UTC ISO-8601 with a ``Z`` suffix (naive values are assumed UTC)."""
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[
    datetime,
    # JSON output only; python-mode dumps keep a real datetime for internal consumers.
    PlainSerializer(_to_utc_z, return_type=str, when_used="json"),
    # Pin the serialization-mode schema so FastAPI doesn't split the model into
    # -Input / -Output variants.
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]


def _normalize_email(value: str) -> str:
    return value.strip().lower()


# Cognito treats the email username case-insensitively; canonicalize at the boundary so the
# Cognito username and the local row always agree.
NormalizedEmail = Annotated[EmailStr, AfterValidator(_normalize_email)]

# Opt-out of BaseSchema's global strip for values that must round-trip byte-for-byte
# (credentials): a password with surrounding whitespace is still that password.
VerbatimStr = Annotated[str, StringConstraints(strip_whitespace=False)]


class BaseSchema(BaseModel):
    """Base for request (``*In``) schemas."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        alias_generator=to_camel,  # snake_case field → camelCase wire key
        validate_by_name=True,  # accept the Python (snake) name on input
        validate_by_alias=True,  # accept the camelCase alias on input
        str_strip_whitespace=True,  # trim request strings; opt out per field with VerbatimStr
        extra="forbid",  # reject unknown request fields
    )


class BaseSchemaOut(BaseSchema):
    """Base for response (``*Out``) schemas, typically built with ``Out.model_validate(model)``."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="ignore",  # responses are built internally; don't forbid
        from_attributes=True,  # validate straight from ORM instances
    )


class ErrorOut(BaseSchemaOut):
    """The one JSON error envelope — built by ``app/core/exception_handlers.py`` and declared on
    every route's error responses through ``app.core.openapi.error_responses``."""

    error: str
    code: ErrorCode
    status_code: int
    correlation_id: str
    # Only present in debug tiers (validation errors, conflict details).
    details: object | None = None
