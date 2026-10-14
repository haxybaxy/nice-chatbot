from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import RunStatus
from app.chat.repository import RunEventRepository, RunRepository
from app.core.exceptions import AppError
from app.core.ui_stream import AbortChunk
from app.db.listen import RUN_CONTROL_CHANNEL, RUN_EVENTS_CHANNEL

CANCELLED_REASON = "cancelled"


class CancelRun:
    """Stop a run. Queued: cancelled here, with the ``abort`` event that ends its stream.
    Running: the worker owns it, so only ``cancel_requested_at`` is set and ``run_control`` is
    notified; the worker aborts and finishes the run. Terminal: nothing to do.

    The run row is locked first so a concurrent claim or finish sees a consistent status.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._runs = RunRepository(session)
        self._events = RunEventRepository(session)

    async def execute(self, *, run_id: UUID) -> None:
        run = await self._runs.lock(run_id)
        if run is None:
            raise AppError.not_found("Run", run_id)
        now = datetime.now(UTC)
        if run.status == RunStatus.QUEUED.value:
            seq = run.last_seq + 1
            run.status = RunStatus.CANCELLED.value
            run.finished_at = now
            run.last_seq = seq
            await self._runs.save(run)
            abort: AbortChunk = {"type": "abort", "reason": CANCELLED_REASON}
            await self._events.add_batch(run.id, seq, [abort])
            await self._runs.notify(RUN_EVENTS_CHANNEL, f"{run.id}:{seq}")
        elif run.status == RunStatus.RUNNING.value:
            if run.cancel_requested_at is None:
                run.cancel_requested_at = now
                await self._runs.save(run)
            await self._runs.notify(RUN_CONTROL_CHANNEL, f"{run.id}:cancel")
