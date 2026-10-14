from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models import OrganizationMemberModel
from app.organizations.repository import OrganizationMemberRepository


class ListMembers:
    def __init__(self, session: AsyncSession) -> None:
        self._members = OrganizationMemberRepository(session)

    async def execute(self, *, organization_id: UUID) -> Sequence[OrganizationMemberModel]:
        return await self._members.list_for_organization(organization_id)
