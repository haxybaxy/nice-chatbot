from collections.abc import AsyncIterator, Sequence
from uuid import UUID

from app.chat.models import TERMINAL_RUN_STATUSES, RunEventModel
from app.chat.repository import RunEventRepository, RunRepository
from app.core.config import chat_settings
from app.core.sse import SSE_DONE, SSE_PING, encode_sse_event
from app.core.ui_stream import TERMINAL_CHUNK_TYPES, ErrorChunk
from app.db.listen import RUN_EVENTS_CHANNEL, Listener, wait_for_event
from app.db.session import SessionScope

# Rows per poll; a full page means more may be waiting, so the loop polls again at once.
_PAGE = 500
_RUN_GONE_TEXT = "The run no longer exists"
_NO_FINAL_EVENT_TEXT = "The assistant stopped without finishing"


class StreamRunEvents:
    """Tail a run's event log as an SSE stream: replay what is persisted after ``after``, then
    follow the log until a terminal chunk (``finish`` / ``error`` / ``abort``).

    Notifications only wake the loop; the log is the data (lost-wakeup rule: clear the event,
    read, then wait with the ping interval as the timeout). Each read is its own short
    transaction so no connection is held across the wait. A run that is terminal without a
    terminal event (lost before it could write one) gets a synthetic ``error`` so the client
    never hangs. Client disconnects cancel the generator.
    """

    def __init__(self, sessions: SessionScope, listener: Listener) -> None:
        self._sessions = sessions
        self._listener = listener

    async def execute(self, *, run_id: UUID, after: int) -> AsyncIterator[bytes]:
        seq = after
        async with self._listener.subscribe(RUN_EVENTS_CHANNEL, str(run_id)) as wakeup:
            while True:
                wakeup.clear()
                status, events = await self._read(run_id, seq)
                finished = False
                for event in events:
                    seq = event.seq
                    yield encode_sse_event(event.seq, event.payload)
                    if event.type in TERMINAL_CHUNK_TYPES:
                        finished = True
                        break
                if finished:
                    break
                if len(events) == _PAGE:
                    continue
                if status is None or status in TERMINAL_RUN_STATUSES:
                    error: ErrorChunk = {
                        "type": "error",
                        "errorText": _RUN_GONE_TEXT if status is None else _NO_FINAL_EVENT_TEXT,
                    }
                    yield encode_sse_event(seq + 1, error)
                    break
                if not await wait_for_event(wakeup, chat_settings.chat_sse_ping_interval_s):
                    yield SSE_PING
        yield SSE_DONE

    async def _read(self, run_id: UUID, after: int) -> tuple[str | None, Sequence[RunEventModel]]:
        # Status before events: a run that turns terminal between the two reads then shows its
        # terminal event in the (later) event read, never a terminal status with a stale log.
        async with self._sessions() as session:
            status = await RunRepository(session).get_status(run_id)
            events = await RunEventRepository(session).list_after(run_id, after, limit=_PAGE)
        return status, events
