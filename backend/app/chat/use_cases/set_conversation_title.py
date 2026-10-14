from uuid import UUID

from app.chat.models import ConversationModel
from app.chat.repository import ConversationRepository
from app.db.session import SessionScope


class SetConversationTitle:
    """Give an untitled conversation its generated title. A title the user (or an earlier run) set
    in the meantime wins: the generated one is only written when the column is still empty."""

    def __init__(self, sessions: SessionScope) -> None:
        self._sessions = sessions

    async def execute(self, *, conversation_id: UUID, title: str) -> ConversationModel | None:
        async with self._sessions() as session:
            conversations = ConversationRepository(session)
            conversation = await conversations.lock(conversation_id)
            if conversation is None or conversation.title is not None:
                return conversation
            conversation.title = title
            return await conversations.save(conversation)
