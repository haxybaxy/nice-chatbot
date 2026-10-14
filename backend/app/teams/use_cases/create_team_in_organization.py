from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.organizations.models import OrganizationMemberModel
from app.organizations.use_cases.get_organization import GetOrganization
from app.teams.models import TeamModel
from app.teams.repository import TeamRepository
from app.teams.use_cases.create_team import CreateTeam
from app.users.models import UserModel


class CreateTeamInOrganization:
    """Create a team on behalf of an organization member (who becomes its first member).

    ``membership`` is the caller's — resolved by the route's dependency, so the organization
    check has already happened. Names are unique per organization (409).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._get_organization = GetOrganization(session)
        self._create_team = CreateTeam(session)
        self._teams = TeamRepository(session)

    async def execute(self, *, membership: OrganizationMemberModel, name: str, creator: UserModel) -> TeamModel:
        if await self._teams.get_by_name(membership.organization_id, name) is not None:
            raise AppError.conflict("A team with this name already exists in the organization")
        organization = await self._get_organization.execute(organization_id=membership.organization_id)
        return await self._create_team.execute(organization=organization, name=name, creator=creator)
