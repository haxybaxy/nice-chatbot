from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from app.chat.models import RunStatus
from app.chat.use_cases.finish_run import FinishRun
from app.chat.use_cases.generate_title import GenerateTitle
from app.chat.use_cases.load_turn import LoadTurn, TurnInput
from app.chat.use_cases.record_run_events import RecordRunEvents
from app.chat.use_cases.record_run_trace import RecordRunTrace
from app.chat.use_cases.save_assistant_message import SaveAssistantMessage
from app.chat.use_cases.set_conversation_title import SetConversationTitle
from app.chat.use_cases.watch_run_lease import WatchRunLease
from app.core.agent.checkpointer import Checkpointer
from app.core.agent.events import MappedEvent, RunFinished, StepCompleted, UIChunkEvent
from app.core.agent.state import AgentLimits
from app.core.agent.turn_graphs import TurnPrompt, TurnSetup, TurnStream, chat_turn, research_turn
from app.core.agent.turn_support import (
    LEASE_LOST,
    WEB_TOOLS,
    TurnProgress,
    TurnSink,
    await_title,
    enabled_tools,
    lease_lost,
    outcome_of,
    sources_of,
)
from app.core.config import chat_settings, settings, worker_settings
from app.core.exceptions import AppError, ErrorCode
from app.core.llm.catalog import ModelSpec, estimate_cost_usd, model_catalog
from app.core.llm.chat_models import ChatModelFactory
from app.core.llm.history import dump_turn
from app.core.logging_config import get_logger
from app.core.observability import Tracer, trace_id_for_run
from app.core.sandbox import SandboxClient
from app.core.search import SearchClient
from app.core.tools.base import RunContext, ToolBudget
from app.core.tools.registry import ToolRegistry
from app.core.ui_stream import CancelToken, UIChunk, data_chunk, is_terminal
from app.db.listen import Listener
from app.db.session import SessionScope

logger = get_logger(__name__)

RUN_TIMEOUT_TEXT = "The response took too long"
SHUTDOWN_TEXT = "The worker is shutting down"
SHUTDOWN_ERROR = "worker shutting down"
UNEXPECTED_TEXT = "The assistant failed unexpectedly"
RESEARCH_MODE = "deep_research"


class RunAssistantTurn:
    """Drive one claimed run from its graph to its terminal row — the worker's unit of work.

    Load the run (``LoadTurn``), create or reuse its assistant message and announce it
    (``start{messageId}``), keep the lease alive and watch for cancel (``WatchRunLease``), start the
    title in the background when the conversation has none, open the trace, build the chat or
    research stream (``turn_graphs``) and consume it under the wall clock: chunks go to the
    ``TurnSink`` (coalesced ``run_event`` rows + NOTIFY), every ``StepCompleted`` upserts the
    assistant message's ``parts`` / ``provider_messages`` / usage, and ``RunFinished`` closes the run
    with the status the mapper's terminal chunk already announced. A later attempt resumes the
    LangGraph thread, emits ``reset-step`` when the previous attempt died inside a model step, and
    keeps everything that attempt persisted.

    Failures are mapped once, here: the wall clock → ``error`` "took too long" + ``failed``; worker
    shutdown (the task is cancelled) → best-effort ``error`` + ``failed`` "worker shutting down",
    then the cancellation propagates; a lost lease → stop without another write (the run is
    someone else's now); anything else → ``error`` + ``failed``. The checkpoint thread is deleted
    after every terminal write and the tracer flushed.
    """

    def __init__(
        self,
        sessions: SessionScope,
        llm: ChatModelFactory,
        tools: ToolRegistry,
        tracer: Tracer,
        checkpointer: Checkpointer,
        listener: Listener,
        search: SearchClient | None,
        sandbox: SandboxClient | None,
    ) -> None:
        self._sessions = sessions
        self._llm = llm
        self._tools = tools
        self._tracer = tracer
        self._checkpointer = checkpointer
        self._listener = listener
        self._search = search
        self._sandbox = sandbox

    async def execute(self, *, run_id: UUID, worker_id: str) -> None:
        try:
            turn = await LoadTurn(self._sessions).execute(run_id=run_id, worker_id=worker_id)
        except AppError as error:
            await self._abort_unloaded(run_id, worker_id, error)
            return
        if turn is None:
            logger.warning("run is not leased to this worker, skipping", run_id=str(run_id), worker_id=worker_id)
            return
        progress = await self._start(turn)
        try:
            await self._run(turn, progress)
        except TimeoutError:
            await self._fail(turn, progress, RUN_TIMEOUT_TEXT)
        except asyncio.CancelledError:
            await self._fail(turn, progress, SHUTDOWN_TEXT, error=SHUTDOWN_ERROR, wait_title=False)
            raise
        except AppError as error:
            await self._fail(turn, progress, error.message)
        except Exception as error:
            logger.exception("assistant turn crashed", run_id=str(run_id), error=repr(error))
            await self._fail(turn, progress, UNEXPECTED_TEXT)
        finally:
            await self._close(turn, progress)

    # ── Setup ────────────────────────────────────────────────────────────────

    async def _start(self, turn: TurnInput) -> TurnProgress:
        """The assistant message row, the run context, the sink and the background tasks."""
        message = await SaveAssistantMessage(self._sessions).execute(run_id=turn.run_id, worker_id=turn.worker_id)
        limits = AgentLimits.from_settings()
        ctx = RunContext(
            run_id=turn.run_id,
            conversation_id=turn.conversation_id,
            user_id=turn.user_id,
            team_id=turn.team_id,
            attempt=turn.attempt,
            cancel=CancelToken(),
            tracer=self._tracer,
            budget=ToolBudget(max_tool_calls=limits.max_tool_calls),
            search=self._search,
            sandbox=self._sandbox,
        )
        ctx.sources.seed(sources_of(message.parts))
        sink = TurnSink(
            lambda chunks: self._record(turn, ctx, chunks),
            ctx=ctx,
            prior=turn.prior_chunks,
            flush_interval_ms=worker_settings.worker_event_flush_ms,
        )
        progress = TurnProgress(
            sink=sink,
            ctx=ctx,
            provider_messages=list(message.provider_messages or []),
            base_input_tokens=message.input_tokens or 0,
            base_output_tokens=message.output_tokens or 0,
        )
        progress.watcher = asyncio.create_task(
            WatchRunLease(self._sessions, self._listener).execute(
                run_id=turn.run_id, worker_id=turn.worker_id, cancel=ctx.cancel
            ),
            name=f"lease-{turn.run_id}",
        )
        if turn.title_needed:
            progress.title = asyncio.create_task(
                GenerateTitle(self._llm).execute(text=turn.first_user_text), name=f"title-{turn.run_id}"
            )
        if not turn.started:
            await sink.emit({"type": "start", "messageId": str(message.id)})
        return progress

    def _setup(self, turn: TurnInput, ctx: RunContext, spec: ModelSpec) -> TurnSetup:
        """What both modes need; ``callbacks()`` is built inside the trace context, so call it there."""
        return TurnSetup(
            llm=self._llm,
            tools=self._tools,
            catalog=model_catalog(),
            spec=spec,
            effort=turn.effort,
            ctx=ctx,
            limits=AgentLimits.from_settings(),
            saver=self._checkpointer.saver,
            callbacks=self._tracer.callbacks(),
            resume=turn.attempt > 1,
        )

    async def _stream(self, turn: TurnInput, progress: TurnProgress, spec: ModelSpec) -> TurnStream:
        setup = self._setup(turn, progress.ctx, spec)
        tool_names = enabled_tools(turn.options)
        if turn.mode == RESEARCH_MODE:
            prompt = self._prompt(turn, tool_names | WEB_TOOLS)
            return await research_turn(setup, prompt, question=turn.question)
        return await chat_turn(setup, self._prompt(turn, tool_names))

    @staticmethod
    def _prompt(turn: TurnInput, tool_names: set[str]) -> TurnPrompt:
        return TurnPrompt(
            product_name=settings.project_name,
            workspace_name=turn.workspace_name,
            user_display_name=turn.user_display_name,
            today=datetime.now(UTC).date(),
            enabled_tools=tool_names,
            history=turn.history,
        )

    # ── The run ──────────────────────────────────────────────────────────────

    async def _run(self, turn: TurnInput, progress: TurnProgress) -> None:
        spec = model_catalog().get(turn.model)
        progress.spec = spec
        with self._tracer.run_context(
            run_id=turn.run_id,
            conversation_id=turn.conversation_id,
            user_id=turn.user_id,
            team_id=turn.team_id,
            mode=turn.mode,
            model=spec.id,
            attempt=turn.attempt,
        ) as trace_id:
            if turn.trace_id is None:
                await self._write(
                    progress.ctx,
                    lambda: RecordRunTrace(self._sessions).execute(
                        run_id=turn.run_id, worker_id=turn.worker_id, trace_id=trace_id or trace_id_for_run(turn.run_id)
                    ),
                )
            stream = await self._stream(turn, progress, spec)
            if turn.open_step:
                await progress.sink.emit({"type": "reset-step"})
            try:
                async with asyncio.timeout(stream.timeout_s):
                    async for event in stream.events:
                        await self._handle(turn, progress, event)
            finally:
                await stream.events.aclose()  # a consumer that stops early still closes the graph

    async def _handle(self, turn: TurnInput, progress: TurnProgress, event: MappedEvent) -> None:
        if isinstance(event, UIChunkEvent):
            await self._emit(turn, progress, event.chunk)
        elif isinstance(event, StepCompleted):
            await self._step(turn, progress, event)
        else:
            await self._finished(turn, progress, event)

    async def _emit(self, turn: TurnInput, progress: TurnProgress, chunk: UIChunk) -> None:
        if is_terminal(chunk):
            await self._emit_title(turn, progress, wait=True)
        await progress.sink.emit(chunk)

    async def _step(self, turn: TurnInput, progress: TurnProgress, step: StepCompleted) -> None:
        await progress.sink.flush()
        progress.steps += 1
        progress.usage = step.usage
        progress.provider_messages = [*progress.provider_messages, *dump_turn(step.messages)]
        await self._save(turn, progress, with_provider_messages=True)

    async def _finished(self, turn: TurnInput, progress: TurnProgress, finished: RunFinished) -> None:
        await progress.sink.flush()
        progress.usage = finished.usage
        await self._save(turn, progress)
        outcome = outcome_of(finished)
        await self._finish(turn, progress, RunStatus(outcome.status), outcome.error)

    async def _emit_title(self, turn: TurnInput, progress: TurnProgress, *, wait: bool) -> None:
        task = progress.title
        if task is None:
            return
        progress.title = None
        title = await await_title(task, timeout_s=chat_settings.chat_title_timeout_s if wait else 0)
        if title is None:
            logger.warning("conversation title not ready in time", run_id=str(turn.run_id))
            return
        await progress.sink.emit(data_chunk("conversation-title", {"title": title}, transient=True))
        await SetConversationTitle(self._sessions).execute(conversation_id=turn.conversation_id, title=title)

    # ── Terminal paths ───────────────────────────────────────────────────────

    async def _fail(
        self, turn: TurnInput, progress: TurnProgress, text: str, *, error: str | None = None, wait_title: bool = True
    ) -> None:
        """Close a run the graph did not close itself: ``error`` chunk, the parts so far, ``failed``."""
        await self._emit_title(turn, progress, wait=wait_title)
        await progress.sink.emit({"type": "error", "errorText": text})
        await self._save(turn, progress)
        await self._finish(turn, progress, RunStatus.FAILED, error or text)

    async def _abort_unloaded(self, run_id: UUID, worker_id: str, error: AppError) -> None:
        """A run that cannot even start (its user or conversation is gone): one ``error`` row and ``failed``."""
        logger.warning("run cannot start", run_id=str(run_id), error=error.message)
        await RecordRunEvents(self._sessions).execute(
            run_id=run_id, worker_id=worker_id, chunks=[{"type": "error", "errorText": error.message}]
        )
        await FinishRun(self._sessions).execute(
            run_id=run_id, worker_id=worker_id, status=RunStatus.FAILED, error=error.message
        )

    async def _close(self, turn: TurnInput, progress: TurnProgress) -> None:
        await progress.cancel_tasks()
        if not progress.sink.closed:
            await self._checkpointer.delete_thread(str(turn.run_id))
        self._tracer.flush()

    # ── Fenced writes ────────────────────────────────────────────────────────

    async def _write(self, ctx: RunContext, write: Callable[[], Awaitable[object]]) -> None:
        """One lease-fenced write; a conflict means the lease is gone and ends every further write."""
        if lease_lost(ctx):
            return
        try:
            await write()
        except AppError as error:
            if error.code is not ErrorCode.CONFLICT:
                raise
            logger.warning("run lease lost; nothing more is written", run_id=str(ctx.run_id))
            ctx.cancel.request(LEASE_LOST)

    async def _record(self, turn: TurnInput, ctx: RunContext, chunks: Sequence[UIChunk]) -> None:
        await self._write(
            ctx,
            lambda: RecordRunEvents(self._sessions).execute(
                run_id=turn.run_id, worker_id=turn.worker_id, chunks=chunks
            ),
        )

    async def _save(self, turn: TurnInput, progress: TurnProgress, *, with_provider_messages: bool = False) -> None:
        await self._write(
            progress.ctx,
            lambda: SaveAssistantMessage(self._sessions).execute(
                run_id=turn.run_id,
                worker_id=turn.worker_id,
                parts=progress.sink.parts(),
                provider_messages=progress.provider_messages if with_provider_messages else None,
                input_tokens=progress.input_tokens,
                output_tokens=progress.output_tokens,
            ),
        )

    async def _finish(self, turn: TurnInput, progress: TurnProgress, status: RunStatus, error: str | None) -> None:
        await self._write(
            progress.ctx,
            lambda: FinishRun(self._sessions).execute(
                run_id=turn.run_id,
                worker_id=turn.worker_id,
                status=status,
                error=error,
                step_count=turn.prior_steps + progress.steps,
                input_tokens=progress.input_tokens,
                output_tokens=progress.output_tokens,
            ),
        )
        self._log_finished(turn, progress, status)

    @staticmethod
    def _log_finished(turn: TurnInput, progress: TurnProgress, status: RunStatus) -> None:
        if progress.sink.closed:
            return  # nothing was written: the run went on elsewhere
        cost = None
        if progress.spec is not None:
            cost = estimate_cost_usd(
                progress.spec,
                input_tokens=progress.input_tokens,
                output_tokens=progress.output_tokens,
                cache_read_tokens=progress.usage.total.cache_read_tokens,
            )
        logger.info(
            "run finished",
            run_id=str(turn.run_id),
            status=status.value,
            attempt=turn.attempt,
            steps=turn.prior_steps + progress.steps,
            input_tokens=progress.input_tokens,
            output_tokens=progress.output_tokens,
            estimated_cost_usd=cost,
        )
