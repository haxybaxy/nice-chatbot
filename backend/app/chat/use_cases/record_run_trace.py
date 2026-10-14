from uuid import UUID

from app.chat.repository import RunRepository
from app.core.exceptions import AppError
from app.db.session import SessionScope


class RecordRunTrace:
    """Store the run's Langfuse trace id once the worker opened the trace. Written on the first
    attempt only (a resumed run keeps its trace); fenced by the lease like every worker write."""

    def __init__(self, sessions: SessionScope) -> None:
        self._sessions = sessions

    async def execute(self, *, run_id: UUID, worker_id: str, trace_id: str) -> None:
        async with self._sessions() as session:
            runs = RunRepository(session)
            run = await runs.lock_owned(run_id, worker_id)
            if run is None:
                raise AppError.conflict("Run lease lost", run_id=str(run_id), worker_id=worker_id)
            if run.trace_id is None:
                run.trace_id = trace_id
                await runs.save(run)
