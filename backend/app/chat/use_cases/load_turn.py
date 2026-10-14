from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast, get_args
from uuid import UUID

from app.chat.models import MessageModel, MessageRole, RunModel, RunStatus
from app.chat.repository import ConversationRepository, MessageRepository, RunEventRepository, RunRepository
from app.core.agent.turn_support import finished_steps, has_open_step, has_started
from app.core.config import Effort, chat_settings, llm_settings
from app.core.exceptions import AppError
from app.core.llm.history import StoredMessage, text_of_parts
from app.core.ui_stream import UI_CHUNK_ADAPTER, UIChunk
from app.db.session import SessionScope
from app.teams.use_cases.get_team import GetTeam
from app.users.use_cases.get_user import GetUser

_EFFORTS: frozenset[str] = frozenset(get_args(Effort))


@dataclass(frozen=True, slots=True)
class TurnInput:
    """Everything a worker needs to drive one run, read in a single short transaction."""

    run_id: UUID
    worker_id: str
    conversation_id: UUID
    team_id: UUID
    user_id: UUID
    attempt: int
    mode: str
    model: str
    effort: Effort
    options: Mapping[str, object]
    trace_id: str | None
    workspace_name: str
    user_display_name: str | None
    title_needed: bool
    # The first user message (what the title is made from) and the latest one (the research question).
    first_user_text: str
    question: str
    history: Sequence[StoredMessage]
    # The event log of earlier attempts (empty on the first) and what it says about where they stopped.
    prior_chunks: Sequence[UIChunk]
    started: bool
    open_step: bool
    prior_steps: int


def _effort_of(run: RunModel) -> Effort:
    return cast("Effort", run.effort) if run.effort in _EFFORTS else llm_settings.llm_default_effort


def _stored(message: MessageModel) -> StoredMessage:
    role = "assistant" if message.role == MessageRole.ASSISTANT.value else "user"
    return StoredMessage(
        role=role,
        parts=message.parts,
        provider=message.provider,
        model=message.model,
        provider_messages=message.provider_messages,
    )


def _user_texts(messages: Sequence[MessageModel]) -> list[str]:
    return [text_of_parts(message.parts) for message in messages if message.role == MessageRole.USER.value]


class LoadTurn:
    """Read a claimed run and its surroundings for the worker: the run (``running`` and leased to
    ``worker_id``, else ``None`` — another worker or the reaper got there first), the conversation,
    team and requesting user, the history as ``StoredMessage`` rows (this run's own assistant
    message excluded, trimmed to ``chat_history_max_messages``) and, on a later attempt, the event
    log the previous attempt left behind."""

    def __init__(self, sessions: SessionScope) -> None:
        self._sessions = sessions

    async def execute(self, *, run_id: UUID, worker_id: str) -> TurnInput | None:
        async with self._sessions() as session:
            run = await RunRepository(session).get_by_id(run_id)
            if run is None or run.status != RunStatus.RUNNING.value or run.worker_id != worker_id:
                return None
            conversation = await ConversationRepository(session).get_by_id(run.conversation_id)
            if conversation is None or run.requested_by is None:
                raise AppError.bad_request("The run's conversation or requesting user no longer exists")
            team = await GetTeam(session).execute(team_id=conversation.team_id)
            user = await GetUser(session).execute(user_id=run.requested_by)
            messages = await MessageRepository(session).list_for_conversation(conversation.id)
            prior: list[UIChunk] = []
            if run.last_seq > 0:
                events = await RunEventRepository(session).list_all(run.id)
                prior = [UI_CHUNK_ADAPTER.validate_python(event.payload) for event in events]
        history = [_stored(message) for message in messages if message.run_id != run.id]
        user_texts = _user_texts(messages)
        return TurnInput(
            run_id=run.id,
            worker_id=worker_id,
            conversation_id=conversation.id,
            team_id=conversation.team_id,
            user_id=user.id,
            attempt=run.attempt,
            mode=run.mode,
            model=run.model,
            effort=_effort_of(run),
            options=dict(run.options),
            trace_id=run.trace_id,
            workspace_name=team.name,
            user_display_name=user.full_name,
            title_needed=conversation.title is None,
            first_user_text=user_texts[0] if user_texts else "",
            question=user_texts[-1] if user_texts else "",
            history=history[-chat_settings.chat_history_max_messages :],
            prior_chunks=prior,
            started=has_started(prior),
            open_step=has_open_step(prior),
            prior_steps=finished_steps(prior),
        )
