from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.chat.use_cases.touch_run import TouchRun
from app.core.agent.turn_support import CANCEL_BY_USER, LEASE_LOST
from app.core.config import worker_settings
from app.core.logging_config import get_logger
from app.core.ui_stream import CancelToken
from app.db.listen import RUN_CONTROL_CHANNEL, Listener, wait_for_event
from app.db.session import SessionScope

logger = get_logger(__name__)


class WatchRunLease:
    """The heartbeat of a running turn: every ``worker_heartbeat_interval_s`` (or at once when
    ``run_control`` fires for the run) extend the lease and read the cancel flag.

    A requested cancel flips the run's cancel token (``"user"``) and the heartbeat goes on so the
    run stays owned while it winds down; a lease that is no longer ours (reaped and re-queued, or
    finished) flips it to ``"lease lost"`` and the watcher stops — nothing may be written after
    that. A database hiccup is retried on the next tick. Runs until cancelled by the orchestrator.
    """

    def __init__(self, sessions: SessionScope, listener: Listener) -> None:
        self._touch = TouchRun(sessions)
        self._listener = listener

    async def execute(self, *, run_id: UUID, worker_id: str, cancel: CancelToken) -> None:
        interval_s = worker_settings.worker_heartbeat_interval_s
        async with self._listener.subscribe(RUN_CONTROL_CHANNEL, str(run_id)) as wakeup:
            while True:
                await wait_for_event(wakeup, interval_s)
                wakeup.clear()
                try:
                    lease = await self._touch.execute(run_id=run_id, worker_id=worker_id)
                except SQLAlchemyError as error:
                    logger.warning("heartbeat failed", run_id=str(run_id), error_type=type(error).__name__)
                    continue
                if not lease.owned:
                    logger.warning("run lease lost", run_id=str(run_id), worker_id=worker_id)
                    cancel.request(LEASE_LOST)
                    return
                if lease.cancel_requested:
                    cancel.request(CANCEL_BY_USER)
