from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ConversationModel
from app.chat.repository import ConversationRepository, RunRepository
from app.core.exceptions import AppError


class DeleteConversation:
    """Delete a conversation with its messages, runs and events (cascades). Refused while a run
    is active — cancel it first, so no worker is left writing into a deleted conversation."""

    def __init__(self, session: AsyncSession) -> None:
        self._conversations = ConversationRepository(session)
        self._runs = RunRepository(session)

    async def execute(self, *, conversation: ConversationModel) -> None:
        if await self._runs.get_active(conversation.id) is not None:
            raise AppError.conflict("A run is active in this conversation; cancel it first")
        await self._conversations.delete(conversation)
