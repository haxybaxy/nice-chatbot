from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ConversationModel, ConversationVisibility
from app.chat.repository import ConversationRepository
from app.chat.use_cases.create_message import CreateMessage, NewMessage
from app.users.models import UserModel


class CreateConversation:
    """Open a conversation in a team; with ``message`` the first user turn is queued as well.

    The route's dependency has verified that ``creator`` is a member of ``team_id``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._conversations = ConversationRepository(session)
        self._create_message = CreateMessage(session)

    async def execute(
        self,
        *,
        team_id: UUID,
        creator: UserModel,
        title: str | None,
        visibility: ConversationVisibility,
        message: NewMessage | None,
    ) -> ConversationModel:
        conversation = await self._conversations.add(
            ConversationModel(team_id=team_id, created_by=creator.id, title=title, visibility=visibility.value)
        )
        if message is not None:
            await self._create_message.execute(conversation_id=conversation.id, author=creator, message=message)
        return conversation
