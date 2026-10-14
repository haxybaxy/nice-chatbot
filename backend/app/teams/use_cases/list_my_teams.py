from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.teams.models import TeamModel
from app.teams.repository import TeamRepository


class ListMyTeams:
    def __init__(self, session: AsyncSession) -> None:
        self._teams = TeamRepository(session)

    async def execute(self, *, user_id: UUID) -> Sequence[TeamModel]:
        return await self._teams.list_for_user(user_id)
