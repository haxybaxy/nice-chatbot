from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import RunModel
from app.chat.repository import RunRepository
from app.core.exceptions import AppError


class GetRun:
    def __init__(self, session: AsyncSession) -> None:
        self._runs = RunRepository(session)

    async def execute(self, *, run_id: UUID) -> RunModel:
        run = await self._runs.get_by_id(run_id)
        if run is None:
            raise AppError.not_found("Run", run_id)
        return run
