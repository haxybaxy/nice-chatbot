"""The chat run worker (composition root). Run with ``python -m app.worker``.

One process, one :class:`Worker`: it claims queued runs from the ``run`` table (``ClaimRun``,
``FOR UPDATE SKIP LOCKED``), drives each through ``RunAssistantTurn`` as its own task — at most
``WORKER_CONCURRENCY`` at a time — and sleeps on ``LISTEN run_queue`` (bounded by
``WORKER_POLL_INTERVAL_S``) when the queue is empty. A reaper task re-queues or fails runs whose
worker stopped heartbeating (``ReapStaleRuns``) and deletes uploads never bound to a message
(``ReapOrphanAttachments``). SIGTERM / SIGINT set the stop event: the loop
stops claiming, the reaper finishes the pass it is in and exits, running turns are cancelled and
each one closes its run (partial message persisted, ``error`` chunk, ``failed`` "worker shutting
down") within ``WORKER_SHUTDOWN_GRACE_S``; then the tracer, the search client, the checkpointer
pool, the listener and the engine are shut. A stop only ever interrupts a wait (the slot, the
listener, the reaper's sleep), never a database statement: a statement cancelled mid-flight
leaves its connection invalid.

Nothing under ``app/`` imports this module (guard); ``main`` is the only place the process-wide
singletons (``default_*``) are assembled, so tests drive :class:`Worker` with fakes.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from collections.abc import Awaitable
from dataclasses import dataclass

from app.attachments.use_cases.reap_orphan_attachments import ReapOrphanAttachments
from app.chat.use_cases.claim_run import ClaimRun
from app.chat.use_cases.reap_stale_runs import ReapStaleRuns
from app.chat.use_cases.run_assistant_turn import RunAssistantTurn
from app.core.agent.checkpointer import Checkpointer, default_checkpointer
from app.core.config import worker_settings
from app.core.llm.chat_models import ChatModelFactory, default_chat_model_factory
from app.core.logging_config import configure_logging, get_logger
from app.core.observability import Tracer, default_tracer
from app.core.sandbox import SandboxClient, default_sandbox_client
from app.core.search import SearchClient, close_search_client, default_search_client
from app.core.tools.registry import ToolRegistry, default_tool_registry
from app.db.listen import RUN_QUEUE_CHANNEL, Listener, get_listener
from app.db.session import SessionScope, engine, session_scope

logger = get_logger(__name__)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
# How long the claim loop backs off after a database error before trying again.
_CLAIM_RETRY_S = 1.0


@dataclass(frozen=True, slots=True)
class WorkerDeps:
    """Everything a worker talks to; ``main`` passes the process singletons, tests pass fakes."""

    sessions: SessionScope
    listener: Listener
    llm: ChatModelFactory
    tools: ToolRegistry
    tracer: Tracer
    checkpointer: Checkpointer
    search: SearchClient | None
    sandbox: SandboxClient | None


@dataclass(frozen=True, slots=True)
class WorkerOptions:
    concurrency: int = worker_settings.worker_concurrency
    poll_interval_s: float = worker_settings.worker_poll_interval_s
    reaper_interval_s: float = worker_settings.worker_reaper_interval_s
    shutdown_grace_s: float = worker_settings.worker_shutdown_grace_s


class Worker:
    def __init__(self, worker_id: str, deps: WorkerDeps, *, stop: asyncio.Event, options: WorkerOptions) -> None:
        self._worker_id = worker_id
        self._deps = deps
        self._stop = stop
        self._options = options
        self._claim = ClaimRun(deps.sessions)
        self._reap = ReapStaleRuns(deps.sessions)
        self._reap_orphans = ReapOrphanAttachments(deps.sessions)
        self._turn = RunAssistantTurn(
            deps.sessions,
            deps.llm,
            deps.tools,
            deps.tracer,
            deps.checkpointer,
            deps.listener,
            deps.search,
            deps.sandbox,
        )
        self._slots = asyncio.Semaphore(options.concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

    async def serve(self) -> None:
        """Claim and dispatch until the stop event is set, then drain. The reaper runs alongside."""
        reaper = asyncio.create_task(self._reap_forever(), name="reaper")
        try:
            while not self._stop.is_set():
                await self._claim_once()
        finally:
            # Also when serve() itself was cancelled: the reaper watches the event, ends its current
            # pass and exits on its own — it is never cancelled mid-statement.
            self._stop.set()
            await asyncio.gather(reaper, return_exceptions=True)
            await self._drain()

    async def _claim_once(self) -> None:
        """One iteration: wait for a free slot, claim a run and start it, or sleep until woken."""
        if not await self._until_stop(self._slots.acquire()):
            return
        try:
            run = await self._claim.execute(worker_id=self._worker_id)
        except Exception as error:  # noqa: BLE001 — the queue is unreachable: back off, keep serving
            self._slots.release()
            logger.warning("claim failed", error_type=type(error).__name__, retry_in_s=_CLAIM_RETRY_S)
            await self._until_stop(asyncio.sleep(_CLAIM_RETRY_S))
            return
        if run is None:
            self._slots.release()
            await self._until_stop(self._deps.listener.wait(RUN_QUEUE_CHANNEL, timeout_s=self._options.poll_interval_s))
            return
        logger.info("run claimed", run_id=str(run.id), attempt=run.attempt, mode=run.mode, model=run.model)
        task = asyncio.create_task(self._turn.execute(run_id=run.id, worker_id=self._worker_id), name=f"run-{run.id}")
        self._tasks.add(task)
        task.add_done_callback(self._on_done)

    def _on_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        self._slots.release()
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("run task failed", task=task.get_name(), error=repr(error))

    async def _until_stop(self, operation: Awaitable[object]) -> bool:
        """Await ``operation`` unless the stop event fires first; ``False`` when it did."""
        stopping = asyncio.ensure_future(self._stop.wait())
        pending = asyncio.ensure_future(operation)
        done, _ = await asyncio.wait({stopping, pending}, return_when=asyncio.FIRST_COMPLETED)
        for task in (stopping, pending):
            if task not in done:
                task.cancel()
        await asyncio.gather(stopping, pending, return_exceptions=True)
        return pending in done and not pending.cancelled()

    async def _reap_forever(self) -> None:
        """Every ``reaper_interval_s`` until the stop event: stale runs, then orphan attachments."""
        while await self._until_stop(asyncio.sleep(self._options.reaper_interval_s)):
            try:
                reaped = await self._reap.execute()
                orphans = await self._reap_orphans.execute()
            except Exception as error:  # noqa: BLE001 — the reaper must outlive a database hiccup
                logger.warning("reaper failed", error_type=type(error).__name__)
                continue
            if reaped:
                logger.warning("reaped stale runs", count=reaped)
            if orphans:
                logger.info("swept orphan attachments", count=orphans)

    async def _drain(self) -> None:
        """Cancel the running turns and give each ``shutdown_grace_s`` to close its run."""
        tasks = set(self._tasks)
        if not tasks:
            return
        logger.info("cancelling running turns", count=len(tasks), grace_s=self._options.shutdown_grace_s)
        for task in tasks:
            task.cancel()
        _, pending = await asyncio.wait(tasks, timeout=self._options.shutdown_grace_s)
        if pending:
            logger.error("turns did not finish within the grace period", count=len(pending))


async def main() -> None:
    configure_logging()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    checkpointer = default_checkpointer()
    await checkpointer.open()
    listener = get_listener()
    await listener.start()
    tracer = default_tracer()
    deps = WorkerDeps(
        sessions=session_scope,
        listener=listener,
        llm=default_chat_model_factory(),
        tools=default_tool_registry(),
        tracer=tracer,
        checkpointer=checkpointer,
        search=default_search_client(),
        sandbox=default_sandbox_client(),
    )
    options = WorkerOptions()
    logger.info(
        "worker started",
        worker_id=WORKER_ID,
        concurrency=options.concurrency,
        listening=listener.listening,
        tools=deps.tools.names(),
    )
    try:
        await Worker(WORKER_ID, deps, stop=stop, options=options).serve()
    finally:
        logger.info("worker stopping", worker_id=WORKER_ID)
        tracer.shutdown()
        await close_search_client()
        await checkpointer.close()
        await listener.stop()
        await engine.dispose()
        logger.info("worker stopped", worker_id=WORKER_ID)


if __name__ == "__main__":
    asyncio.run(main())
