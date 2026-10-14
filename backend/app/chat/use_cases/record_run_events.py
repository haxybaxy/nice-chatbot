from collections.abc import Sequence
from uuid import UUID

from app.chat.repository import RunEventRepository, RunRepository
from app.core.exceptions import AppError
from app.core.ui_stream import UIChunk
from app.db.listen import RUN_EVENTS_CHANNEL
from app.db.session import SessionScope


class RecordRunEvents:
    """Append a batch of chunks to the run's log at ``last_seq + 1 …`` and wake its readers.

    Fenced by the lease: when the run is no longer running under ``worker_id`` nothing is written
    and ``AppError.conflict`` tells the worker to stop. Returns the new ``last_seq``.
    """

    def __init__(self, sessions: SessionScope) -> None:
        self._sessions = sessions

    async def execute(self, *, run_id: UUID, worker_id: str, chunks: Sequence[UIChunk]) -> int:
        async with self._sessions() as session:
            runs = RunRepository(session)
            run = await runs.lock_owned(run_id, worker_id)
            if run is None:
                raise AppError.conflict("Run lease lost", run_id=str(run_id), worker_id=worker_id)
            if not chunks:
                return run.last_seq
            first_seq = run.last_seq + 1
            await RunEventRepository(session).add_batch(run.id, first_seq, chunks)
            run.last_seq = first_seq + len(chunks) - 1
            await runs.save(run)
            await runs.notify(RUN_EVENTS_CHANNEL, f"{run.id}:{run.last_seq}")
            return run.last_seq
