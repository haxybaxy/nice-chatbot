from datetime import UTC, datetime, timedelta

from app.chat.models import MessageModel, MessageRole, RunModel, RunStatus
from app.chat.repository import MessageRepository, RunEventRepository, RunRepository
from app.core.config import worker_settings
from app.core.logging_config import get_logger
from app.core.ui_fold import fold_parts
from app.core.ui_stream import UI_CHUNK_ADAPTER, ErrorChunk
from app.db.listen import RUN_EVENTS_CHANNEL, RUN_QUEUE_CHANNEL
from app.db.session import SessionScope

logger = get_logger(__name__)

INTERRUPTED_TEXT = "The assistant was interrupted"


class ReapStaleRuns:
    """Recover runs whose worker stopped heartbeating (``worker_stale_after_s``).

    First loss: re-queue as attempt 2, keeping the event log and the assistant message so the
    next worker resumes (``reset-step`` + LangGraph checkpoint). Second loss: fail it — the
    message is rebuilt from the event log (``fold_parts``) and an ``error`` chunk closes the
    stream. Rows are locked ``SKIP LOCKED`` so concurrent reapers never fight. Returns how many
    runs were reaped.
    """

    def __init__(self, sessions: SessionScope) -> None:
        self._sessions = sessions

    async def execute(self) -> int:
        threshold = datetime.now(UTC) - timedelta(seconds=worker_settings.worker_stale_after_s)
        async with self._sessions() as session:
            runs = RunRepository(session)
            stale = await runs.lock_stale(threshold)
            for run in stale:
                if run.attempt == 1:
                    await self._requeue(run, runs)
                else:
                    await self._fail(run, runs, RunEventRepository(session), MessageRepository(session))
            return len(stale)

    async def _requeue(self, run: RunModel, runs: RunRepository) -> None:
        logger.warning("re-queuing stale run", run_id=str(run.id), lost_worker_id=run.worker_id)
        run.status = RunStatus.QUEUED.value
        run.attempt += 1
        run.worker_id = None
        run.heartbeat_at = None
        await runs.save(run)
        await runs.notify(RUN_QUEUE_CHANNEL, str(run.id))

    async def _fail(
        self, run: RunModel, runs: RunRepository, events: RunEventRepository, messages: MessageRepository
    ) -> None:
        logger.error("failing stale run", run_id=str(run.id), lost_worker_id=run.worker_id, attempt=run.attempt)
        log = await events.list_all(run.id)
        parts = fold_parts(UI_CHUNK_ADAPTER.validate_python(event.payload) for event in log)
        message = await messages.get_by_run(run.id)
        if message is not None:
            message.parts = parts
            await messages.save(message)
        elif parts:
            await messages.add(
                MessageModel(
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                    created_by=None,
                    role=MessageRole.ASSISTANT.value,
                    position=await messages.next_position(run.conversation_id),
                    parts=parts,
                    provider=run.provider,
                    model=run.model,
                )
            )
        seq = run.last_seq + 1
        error: ErrorChunk = {"type": "error", "errorText": INTERRUPTED_TEXT}
        await events.add_batch(run.id, seq, [error])
        run.last_seq = seq
        run.status = RunStatus.FAILED.value
        run.error = INTERRUPTED_TEXT
        run.finished_at = datetime.now(UTC)
        await runs.save(run)
        await runs.notify(RUN_EVENTS_CHANNEL, f"{run.id}:{seq}")
