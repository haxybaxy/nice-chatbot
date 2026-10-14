from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import MessageModel, MessageRole, RunMode, RunModel, RunStatus
from app.chat.repository import ConversationRepository, MessageRepository, RunRepository
from app.core.config import llm_settings
from app.core.exceptions import AppError
from app.core.llm.catalog import model_catalog
from app.core.ui_stream import JsonObject
from app.db.listen import RUN_QUEUE_CHANNEL
from app.users.models import UserModel


@dataclass(frozen=True, slots=True)
class NewMessage:
    """What the client sends: text parts plus the run's model, mode and tool switches."""

    texts: tuple[str, ...]
    model: str | None = None
    mode: RunMode = RunMode.CHAT
    web_search: bool = True
    code: bool = False


class CreateMessage:
    """Append a user message and queue the assistant's run, in one transaction.

    The conversation row is locked (``FOR UPDATE``) so two concurrent posts cannot both pass the
    one-active-run check; the partial unique index backs that up. The run is announced with
    ``pg_notify('run_queue')`` inside the same transaction, so a worker only hears about a run
    that is committed.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._conversations = ConversationRepository(session)
        self._messages = MessageRepository(session)
        self._runs = RunRepository(session)

    async def execute(self, *, conversation_id: UUID, author: UserModel, message: NewMessage) -> RunModel:
        conversation = await self._conversations.lock(conversation_id)
        if conversation is None:
            raise AppError.not_found("Conversation", conversation_id)
        if await self._runs.get_active(conversation.id) is not None:
            raise AppError.conflict("A run is already active in this conversation")
        catalog = model_catalog()
        spec = catalog.get(message.model or catalog.default().id)

        parts: list[JsonObject] = [{"type": "text", "text": text} for text in message.texts]
        await self._messages.add(
            MessageModel(
                conversation_id=conversation.id,
                created_by=author.id,
                role=MessageRole.USER.value,
                position=await self._messages.next_position(conversation.id),
                parts=parts,
            )
        )
        run = await self._runs.add(
            RunModel(
                conversation_id=conversation.id,
                requested_by=author.id,
                status=RunStatus.QUEUED.value,
                mode=message.mode.value,
                model=spec.id,
                provider=spec.provider,
                effort=llm_settings.llm_default_effort,
                options={"web_search": message.web_search, "code": message.code},
                trace_id=None,
            )
        )
        conversation.last_message_at = datetime.now(UTC)
        conversation.model = spec.id
        await self._conversations.save(conversation)
        await self._runs.notify(RUN_QUEUE_CHANNEL, str(run.id))
        await self._conversations.refresh_active_run(conversation)
        return run
