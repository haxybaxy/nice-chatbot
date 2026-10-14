from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.chat.repository import RunRepository
from app.db.session import SessionScope


@dataclass(frozen=True, slots=True)
class RunLease:
    # False: the run is no longer this worker's (reaped and re-queued, or finished) — stop.
    owned: bool
    cancel_requested: bool


class TouchRun:
    """Heartbeat: extend the lease and learn whether a cancel was requested, in one statement."""

    def __init__(self, sessions: SessionScope) -> None:
        self._sessions = sessions

    async def execute(self, *, run_id: UUID, worker_id: str) -> RunLease:
        async with self._sessions() as session:
            row = await RunRepository(session).touch(run_id, worker_id, datetime.now(UTC))
        if row is None:
            return RunLease(owned=False, cancel_requested=False)
        return RunLease(owned=True, cancel_requested=row[0] is not None)
