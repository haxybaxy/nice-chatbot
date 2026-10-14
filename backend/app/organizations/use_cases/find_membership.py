from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models import OrganizationMemberModel
from app.organizations.repository import OrganizationMemberRepository


class FindMembership:
    """Non-raising membership lookup — the organizations domain's public answer to "is this
    user in that organization, and as what?" for other domains' dependencies and rules."""

    def __init__(self, session: AsyncSession) -> None:
        self._members = OrganizationMemberRepository(session)

    async def execute(self, *, organization_id: UUID, user_id: UUID) -> OrganizationMemberModel | None:
        return await self._members.get(organization_id, user_id)
