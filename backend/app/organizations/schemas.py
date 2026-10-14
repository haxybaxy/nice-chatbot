"""HTTP schemas for the organizations API."""

from uuid import UUID

from pydantic import Field, field_validator

from app.core.schemas import BaseSchema, BaseSchemaOut, NormalizedEmail, UtcDatetime
from app.organizations.models import OrganizationRole


class CreateOrganizationIn(BaseSchema):
    name: str = Field(min_length=1, max_length=255)


class OrganizationOut(BaseSchemaOut):
    id: UUID
    name: str
    created_at: UtcDatetime
    updated_at: UtcDatetime


class InviteMemberIn(BaseSchema):
    email: NormalizedEmail
    role: OrganizationRole = OrganizationRole.MEMBER

    @field_validator("role")
    @classmethod
    def _owner_is_not_grantable(cls, value: OrganizationRole) -> OrganizationRole:
        if value is OrganizationRole.OWNER:
            raise ValueError("the owner role cannot be granted")
        return value


class MemberUserOut(BaseSchemaOut):
    id: UUID
    email: str
    full_name: str | None = None


class OrganizationMemberOut(BaseSchemaOut):
    user_id: UUID
    role: OrganizationRole
    created_at: UtcDatetime
    user: MemberUserOut
