from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ConversationModel, ConversationVisibility
from app.chat.repository import ConversationRepository
from app.core.exceptions import AppError
from app.users.models import UserModel


class UpdateConversation:
    """Rename or re-share a conversation. Any reader may retitle; only the creator changes
    visibility (a member must not be able to expose someone's private conversation, nor hide a
    team one)."""

    def __init__(self, session: AsyncSession) -> None:
        self._conversations = ConversationRepository(session)

    async def execute(
        self,
        *,
        conversation: ConversationModel,
        actor: UserModel,
        title: str | None,
        visibility: ConversationVisibility | None,
    ) -> ConversationModel:
        if visibility is not None and visibility.value != conversation.visibility:
            if conversation.created_by != actor.id:
                raise AppError.forbidden("Only the creator can change a conversation's visibility")
            conversation.visibility = visibility.value
        if title is not None:
            conversation.title = title
        return await self._conversations.save(conversation)
