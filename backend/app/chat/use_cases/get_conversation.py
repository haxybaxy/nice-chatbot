from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ConversationModel, MessageModel, MessageRole
from app.chat.repository import MessageRepository


@dataclass(frozen=True, slots=True)
class ConversationDetail:
    conversation: ConversationModel
    messages: Sequence[MessageModel]


class GetConversation:
    """The conversation with its messages — minus the assistant message of a still-active run,
    which the client receives through the run's event stream instead (replayed from seq 0)."""

    def __init__(self, session: AsyncSession) -> None:
        self._messages = MessageRepository(session)

    async def execute(self, *, conversation: ConversationModel) -> ConversationDetail:
        messages = await self._messages.list_for_conversation(conversation.id)
        active = conversation.active_run
        if active is not None:
            messages = [
                message
                for message in messages
                if not (message.run_id == active.id and message.role == MessageRole.ASSISTANT.value)
            ]
        return ConversationDetail(conversation=conversation, messages=messages)
