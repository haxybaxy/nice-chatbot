from collections.abc import Sequence
from uuid import UUID

from app.chat.models import MessageModel, MessageRole
from app.chat.repository import MessageRepository, RunRepository
from app.core.exceptions import AppError
from app.core.ui_stream import JsonObject
from app.db.session import SessionScope


class SaveAssistantMessage:
    """The run's assistant message: created on first call (the worker emits its id in
    ``start.messageId``), reused afterwards — also on a second attempt, which keeps what the
    first attempt persisted. Only the fields passed are replaced (JSONB values are reassigned,
    never mutated). Fenced by the lease like every worker write."""

    def __init__(self, sessions: SessionScope) -> None:
        self._sessions = sessions

    async def execute(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        parts: Sequence[JsonObject] | None = None,
        provider_messages: Sequence[JsonObject] | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> MessageModel:
        async with self._sessions() as session:
            runs = RunRepository(session)
            messages = MessageRepository(session)
            run = await runs.lock_owned(run_id, worker_id)
            if run is None:
                raise AppError.conflict("Run lease lost", run_id=str(run_id), worker_id=worker_id)
            message = await messages.get_by_run(run.id)
            if message is None:
                message = MessageModel(
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                    created_by=None,
                    role=MessageRole.ASSISTANT.value,
                    position=await messages.next_position(run.conversation_id),
                    parts=list(parts or []),
                    provider=run.provider,
                    model=run.model,
                    provider_messages=list(provider_messages) if provider_messages is not None else None,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                return await messages.add(message)
            if parts is not None:
                message.parts = list(parts)
            if provider_messages is not None:
                message.provider_messages = list(provider_messages)
            if input_tokens is not None:
                message.input_tokens = input_tokens
            if output_tokens is not None:
                message.output_tokens = output_tokens
            return await messages.save(message)
