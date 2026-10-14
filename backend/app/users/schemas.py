"""HTTP schemas for the users API."""

from uuid import UUID

from pydantic import Field

from app.core.schemas import BaseSchema, BaseSchemaOut, UtcDatetime


class UserOut(BaseSchemaOut):
    id: UUID
    email: str
    full_name: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class UpdateUserIn(BaseSchema):
    # None means "unchanged"; a name can't be cleared through PATCH (documented gap).
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
