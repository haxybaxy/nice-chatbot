from datetime import UTC, datetime

from app.chat.models import RunModel, RunStatus
from app.chat.repository import RunRepository
from app.db.session import SessionScope


class ClaimRun:
    """Take the oldest queued run for ``worker_id`` (``FOR UPDATE SKIP LOCKED``), marking it
    running with a fresh heartbeat. ``None`` when the queue is empty. A re-queued run keeps its
    original ``started_at``."""

    def __init__(self, sessions: SessionScope) -> None:
        self._sessions = sessions

    async def execute(self, *, worker_id: str) -> RunModel | None:
        async with self._sessions() as session:
            runs = RunRepository(session)
            run = await runs.lock_next_queued()
            if run is None:
                return None
            now = datetime.now(UTC)
            run.status = RunStatus.RUNNING.value
            run.worker_id = worker_id
            run.heartbeat_at = now
            run.started_at = run.started_at or now
            return await runs.save(run)
