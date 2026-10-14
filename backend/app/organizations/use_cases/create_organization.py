from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models import OrganizationMemberModel, OrganizationModel, OrganizationRole
from app.organizations.repository import OrganizationMemberRepository, OrganizationRepository
from app.users.models import UserModel


class CreateOrganization:
    """Create an organization; the creator becomes its owner."""

    def __init__(self, session: AsyncSession) -> None:
        self._organizations = OrganizationRepository(session)
        self._members = OrganizationMemberRepository(session)

    async def execute(self, *, name: str, creator: UserModel) -> OrganizationModel:
        organization = await self._organizations.add(OrganizationModel(name=name, created_by=creator.id))
        await self._members.add(
            OrganizationMemberModel(
                organization_id=organization.id,
                user_id=creator.id,
                role=OrganizationRole.OWNER.value,
                user=creator,
            )
        )
        return organization
