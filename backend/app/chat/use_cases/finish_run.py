from datetime import UTC, datetime
from uuid import UUID

from app.chat.models import TERMINAL_RUN_STATUSES, RunModel, RunStatus
from app.chat.repository import ConversationRepository, RunRepository
from app.core.exceptions import AppError
from app.db.session import SessionScope


class FinishRun:
    """Close a running run with a terminal status after its last event was recorded. Fenced by
    the lease; bumps the conversation's ``last_message_at`` so it sorts as freshly active."""

    def __init__(self, sessions: SessionScope) -> None:
        self._sessions = sessions

    async def execute(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        status: RunStatus,
        error: str | None = None,
        step_count: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> RunModel:
        if status.value not in TERMINAL_RUN_STATUSES:
            raise AppError.bad_request("A run finishes with a terminal status", details={"status": status.value})
        async with self._sessions() as session:
            runs = RunRepository(session)
            run = await runs.lock_owned(run_id, worker_id)
            if run is None:
                raise AppError.conflict("Run lease lost", run_id=str(run_id), worker_id=worker_id)
            now = datetime.now(UTC)
            run.status = status.value
            run.error = error
            run.finished_at = now
            if step_count is not None:
                run.step_count = step_count
            if input_tokens is not None:
                run.input_tokens = input_tokens
            if output_tokens is not None:
                run.output_tokens = output_tokens
            conversation = await ConversationRepository(session).get_by_id(run.conversation_id)
            if conversation is not None:
                conversation.last_message_at = now
            return await runs.save(run)
