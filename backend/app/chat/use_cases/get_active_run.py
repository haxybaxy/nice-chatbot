from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import RunModel
from app.chat.repository import RunRepository
from app.core.exceptions import AppError


class GetActiveRun:
    def __init__(self, session: AsyncSession) -> None:
        self._runs = RunRepository(session)

    async def execute(self, *, conversation_id: UUID) -> RunModel:
        run = await self._runs.get_active(conversation_id)
        if run is None:
            raise AppError.not_found("Active run")
        return run
