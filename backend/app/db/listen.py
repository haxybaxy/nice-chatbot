"""Postgres ``LISTEN``/``NOTIFY`` fan-out — how the API and the worker learn about run activity.

One :class:`PgListener` per process holds a dedicated autocommit psycopg connection (never one
from the SQLAlchemy pool: a pooled connection is bound to a transaction and ``statement_timeout``)
that listens on the three run channels and wakes :class:`asyncio.Event` waiters keyed by
``(channel, key)``, where ``key`` is the first ``:``-separated token of the payload (the run id)
or ``"*"`` for everything on the channel.

Notifications are a wake-up hint, never the data: a reader that must not miss an update follows
the lost-wakeup rule — ``subscribe()`` → ``event.clear()`` → SELECT → wait with a timeout → loop.
A notification that arrives while the connection is down is simply lost, which the timeout
covers (the SSE reader polls at the ping interval, the worker at its poll interval).

Channels and payloads (sent with ``SELECT pg_notify(...)`` in the writer's transaction):

* ``run_queue``: ``<run_id>`` — a run was queued (or re-queued by the reaper).
* ``run_events``: ``<run_id>:<last_seq>`` — new ``run_event`` rows were written.
* ``run_control``: ``<run_id>:cancel`` — a client asked a running run to stop.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import cache
from typing import Annotated, Final, Protocol

import psycopg
from fastapi import Depends
from psycopg import sql
from sqlalchemy.engine import make_url

from app.core.logging_config import get_logger
from app.db.config import db_settings

logger = get_logger(__name__)

RUN_QUEUE_CHANNEL: Final = "run_queue"
RUN_EVENTS_CHANNEL: Final = "run_events"
RUN_CONTROL_CHANNEL: Final = "run_control"
CHANNELS: Final[tuple[str, ...]] = (RUN_QUEUE_CHANNEL, RUN_EVENTS_CHANNEL, RUN_CONTROL_CHANNEL)
ANY_KEY: Final = "*"

# How long `start()` waits for the LISTEN connection before letting the caller fall back to
# polling, and the reconnect backoff when the connection drops.
_CONNECT_WAIT_S = 5.0
_BACKOFF_INITIAL_S = 0.5
_BACKOFF_MAX_S = 30.0


class Listener(Protocol):
    """What run readers depend on; ``PgListener`` is the real one, tests inject a fake."""

    def subscribe(self, channel: str, key: str = ANY_KEY) -> AbstractAsyncContextManager[asyncio.Event]: ...
    async def wait(self, channel: str, key: str = ANY_KEY, *, timeout_s: float) -> bool: ...


async def wait_for_event(event: asyncio.Event, timeout_s: float) -> bool:
    """``True`` when ``event`` was set within ``timeout_s`` seconds, ``False`` on timeout."""
    try:
        await asyncio.wait_for(event.wait(), timeout_s)
    except TimeoutError:
        return False
    return True


class PgListener:
    def __init__(self, conninfo: str, *, channels: tuple[str, ...] = CHANNELS) -> None:
        self._conninfo = conninfo
        self._channels = channels
        self._waiters: dict[tuple[str, str], set[asyncio.Event]] = {}
        self._pump: asyncio.Task[None] | None = None
        self._listening = asyncio.Event()
        self._stopping = False

    @property
    def listening(self) -> bool:
        """The connection is up and every channel is being listened to."""
        return self._listening.is_set()

    async def start(self) -> None:
        """Start the pump task once; wait briefly for the LISTEN to be active.

        Idempotent and lazy — the first subscriber starts it. When the database is unreachable
        the wait times out and the caller proceeds on its poll timeout while the pump keeps
        reconnecting in the background.
        """
        if self._pump is None or self._pump.done():
            self._stopping = False
            self._pump = asyncio.create_task(self._run(), name="pg-listener")
        if not self._listening.is_set() and not await wait_for_event(self._listening, _CONNECT_WAIT_S):
            logger.warning("listener not connected yet; readers fall back to polling")

    async def stop(self) -> None:
        self._stopping = True
        pump, self._pump = self._pump, None
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        self._listening.clear()

    @asynccontextmanager
    async def subscribe(self, channel: str, key: str = ANY_KEY) -> AsyncGenerator[asyncio.Event]:
        """An event set on every notification for ``(channel, key)`` while the block runs."""
        await self.start()
        event = asyncio.Event()
        waiters = self._waiters.setdefault((channel, key), set())
        waiters.add(event)
        try:
            yield event
        finally:
            waiters.discard(event)
            if not waiters:
                self._waiters.pop((channel, key), None)

    async def wait(self, channel: str, key: str = ANY_KEY, *, timeout_s: float) -> bool:
        """Block until a notification for ``(channel, key)`` arrives or ``timeout_s`` passes."""
        async with self.subscribe(channel, key) as event:
            return await wait_for_event(event, timeout_s)

    def _dispatch(self, channel: str, payload: str) -> None:
        key = payload.split(":", 1)[0]
        for waiter_key in ((channel, key), (channel, ANY_KEY)):
            for event in self._waiters.get(waiter_key, ()):
                event.set()

    async def _run(self) -> None:
        backoff = _BACKOFF_INITIAL_S
        while not self._stopping:
            try:
                await self._listen_until_disconnected()
                backoff = _BACKOFF_INITIAL_S
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 — any connection failure: back off and reconnect
                if self._stopping:
                    return
                logger.warning("listener connection lost", error_type=type(error).__name__, retry_in_s=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX_S)
            finally:
                self._listening.clear()

    async def _listen_until_disconnected(self) -> None:
        async with await psycopg.AsyncConnection.connect(self._conninfo, autocommit=True) as conn:
            for channel in self._channels:
                await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(channel)))
            self._listening.set()
            logger.info("listener connected", channels=list(self._channels))
            async for notify in conn.notifies():
                self._dispatch(notify.channel, notify.payload)


def _conninfo() -> str:
    """The application database URL as a libpq connection string (no SQLAlchemy driver prefix)."""
    return make_url(db_settings.database_url).set(drivername="postgresql").render_as_string(hide_password=False)


@cache
def get_listener() -> PgListener:
    """The process-wide listener; built on first use so importing the module opens nothing."""
    return PgListener(_conninfo())


async def get_listener_dep() -> Listener:
    return get_listener()


ListenerDep = Annotated[Listener, Depends(get_listener_dep)]
