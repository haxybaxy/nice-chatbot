from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.organizations.use_cases.find_membership import FindMembership
from app.teams.models import TeamMemberModel, TeamModel
from app.teams.repository import TeamMemberRepository
from app.users.use_cases.find_user_by_email import FindUserByEmail


class AddTeamMember:
    """Add an existing organization member (looked up by email) to a team.

    The route's ``TeamManagerDep`` has already checked that the actor may manage members. A user
    who does not exist and one who is not in the team's organization are both 404: the actor
    learns nothing about accounts outside their organization.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._find_user = FindUserByEmail(session)
        self._find_membership = FindMembership(session)
        self._members = TeamMemberRepository(session)

    async def execute(self, *, team: TeamModel, email: str) -> TeamMemberModel:
        user = await self._find_user.execute(email=email)
        if user is None:
            raise AppError.not_found("User", email)
        if await self._find_membership.execute(organization_id=team.organization_id, user_id=user.id) is None:
            raise AppError.not_found("User", email)
        if await self._members.get(team.id, user.id) is not None:
            raise AppError.conflict("User is already a member of this team")
        return await self._members.add(TeamMemberModel(team_id=team.id, user_id=user.id, team=team, user=user))
