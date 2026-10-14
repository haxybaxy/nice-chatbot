from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models import OrganizationModel
from app.teams.models import TeamMemberModel, TeamModel
from app.teams.repository import TeamMemberRepository, TeamRepository
from app.users.models import UserModel


class CreateTeam:
    """Create a team in an organization; the creator becomes its first member.

    The caller vouches that ``creator`` is a member of ``organization`` (sign-up passes the
    owner it just created).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._teams = TeamRepository(session)
        self._members = TeamMemberRepository(session)

    async def execute(self, *, organization: OrganizationModel, name: str, creator: UserModel) -> TeamModel:
        team = await self._teams.add(TeamModel(organization_id=organization.id, name=name, created_by=creator.id))
        await self._members.add(TeamMemberModel(team_id=team.id, user_id=creator.id))
        return team
