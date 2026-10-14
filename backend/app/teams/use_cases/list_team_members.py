from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.teams.models import TeamMemberModel
from app.teams.repository import TeamMemberRepository


class ListTeamMembers:
    def __init__(self, session: AsyncSession) -> None:
        self._members = TeamMemberRepository(session)

    async def execute(self, *, team_id: UUID) -> Sequence[TeamMemberModel]:
        return await self._members.list_for_team(team_id)
