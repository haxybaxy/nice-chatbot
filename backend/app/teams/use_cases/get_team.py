from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.teams.models import TeamModel
from app.teams.repository import TeamRepository


class GetTeam:
    def __init__(self, session: AsyncSession) -> None:
        self._teams = TeamRepository(session)

    async def execute(self, *, team_id: UUID) -> TeamModel:
        team = await self._teams.get_by_id(team_id)
        if team is None:
            raise AppError.not_found("Team", team_id)
        return team
