from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.teams.models import TeamMemberModel
from app.teams.repository import TeamMemberRepository


class FindTeamMembership:
    """Non-raising lookup: the teams domain's public "is this user in that team?" — used by the
    team routes' dependencies and by the chat domain's conversation access check."""

    def __init__(self, session: AsyncSession) -> None:
        self._members = TeamMemberRepository(session)

    async def execute(self, *, team_id: UUID, user_id: UUID) -> TeamMemberModel | None:
        return await self._members.get(team_id, user_id)
