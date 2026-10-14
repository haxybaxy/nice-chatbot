"""HTTP schemas for the teams API."""

from uuid import UUID

from pydantic import Field

from app.core.schemas import BaseSchema, BaseSchemaOut, NormalizedEmail, UtcDatetime


class CreateTeamIn(BaseSchema):
    name: str = Field(min_length=1, max_length=255)


class TeamOrganizationOut(BaseSchemaOut):
    id: UUID
    name: str


class TeamOut(BaseSchemaOut):
    id: UUID
    organization_id: UUID
    name: str
    created_by: UUID | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    organization: TeamOrganizationOut


class AddTeamMemberIn(BaseSchema):
    email: NormalizedEmail


class TeamMemberUserOut(BaseSchemaOut):
    id: UUID
    email: str
    full_name: str | None = None


class TeamMemberOut(BaseSchemaOut):
    team_id: UUID
    user_id: UUID
    created_at: UtcDatetime
    user: TeamMemberUserOut
