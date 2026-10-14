"""What the worker keeps around one assistant turn: the recording sink, the attempt's progress
and the resume bookkeeping read off a run's event log.

:class:`TurnSink` is the event sink a run writes through. It coalesces through
``BufferedEventSink`` and hands batches to the writer the chat domain injects (``RecordRunEvents``),
but it also remembers every chunk of the run — the earlier attempts' log first, then what this
attempt emits — so ``parts()`` folds the whole run at any step boundary: exactly what the SSE
reader replays and ``useChat`` builds, which keeps ``message.parts`` and the stream in agreement
on a resumed run too. Once the lease is lost (the cancel token says so) nothing further is
recorded or written.

:class:`TurnProgress` is the mutable state of one attempt: the sink, the run context, the
``provider_messages`` accumulated so far, usage, and the background tasks the orchestrator cancels
when it closes. The functions below are pure reads of chunks and parts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from app.core.agent.events import RunFinished
from app.core.agent.usage import RunUsage
from app.core.llm.catalog import ModelSpec
from app.core.tools.base import RunContext, Source
from app.core.ui_fold import fold_parts
from app.core.ui_stream import BufferedEventSink, FlushFn, JsonObject, UIChunk

# `CancelToken.reason` values the worker tells apart: a user's cancel ends the run as `cancelled`,
# a lost lease means another worker owns the run now and this one must not write anything more.
CANCEL_BY_USER: Final = "user"
LEASE_LOST: Final = "lease lost"
WEB_TOOLS: Final[frozenset[str]] = frozenset({"web_search", "web_fetch"})
CODE_TOOL: Final = "run_code"


def lease_lost(ctx: RunContext) -> bool:
    """The run belongs to another worker now (reaped and re-queued, or finished): write nothing more."""
    return ctx.cancel.requested and ctx.cancel.reason == LEASE_LOST


class TurnSink:
    """The run's event sink: coalesced writes plus the full chunk history for folding."""

    def __init__(
        self, write: FlushFn, *, ctx: RunContext, prior: Sequence[UIChunk] = (), flush_interval_ms: int
    ) -> None:
        self.chunks: list[UIChunk] = list(prior)
        self._buffer = BufferedEventSink(write, flush_interval_ms=flush_interval_ms)
        self._ctx = ctx

    @property
    def closed(self) -> bool:
        """The lease is gone: emits and flushes are dropped (another worker owns the run)."""
        return lease_lost(self._ctx)

    async def emit(self, chunk: UIChunk) -> None:
        if self.closed:
            return
        self.chunks.append(chunk)
        await self._buffer.emit(chunk)

    async def flush(self) -> None:
        if not self.closed:
            await self._buffer.flush()

    def parts(self) -> list[JsonObject]:
        """The assistant message's parts as the UI would have folded them from the whole run."""
        return fold_parts(self.chunks)


@dataclass(slots=True)
class TurnProgress:
    """One attempt's mutable state, owned by the orchestrator."""

    sink: TurnSink
    ctx: RunContext
    # `message.provider_messages` so far (earlier attempts included); each step appends its dump.
    provider_messages: list[JsonObject]
    # Tokens persisted by earlier attempts; this attempt's usage is added on top.
    base_input_tokens: int
    base_output_tokens: int
    # Resolved once the run is under way; the cost estimate in the final log line needs it.
    spec: ModelSpec | None = None
    usage: RunUsage = field(default_factory=RunUsage)
    steps: int = 0
    title: asyncio.Task[str] | None = None
    watcher: asyncio.Task[None] | None = None

    @property
    def input_tokens(self) -> int:
        return self.base_input_tokens + self.usage.total.input_tokens

    @property
    def output_tokens(self) -> int:
        return self.base_output_tokens + self.usage.total.output_tokens

    async def cancel_tasks(self) -> None:
        """Stop the lease watcher and a title still in flight; neither outcome matters any more."""
        if self.title is not None:
            self.title.cancel()
            await asyncio.wait({self.title})
        if self.watcher is not None:
            self.watcher.cancel()
            await asyncio.wait({self.watcher})


# ── Outcomes ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Outcome:
    """How a finished stream maps onto the run row."""

    status: str  # succeeded | failed | cancelled
    error: str | None


def outcome_of(finished: RunFinished) -> Outcome:
    """The terminal status for a ``RunFinished``: the mapper already emitted the matching chunk."""
    if finished.error is not None:
        return Outcome("failed", finished.error.message)
    if finished.stop.reason == "cancelled":
        return Outcome("cancelled", None)
    if finished.stop.reason == "error":
        return Outcome("failed", finished.stop.explanation or "The assistant failed")
    return Outcome("succeeded", None)


# ── Reads of the log and the parts ───────────────────────────────────────────


def has_started(chunks: Iterable[UIChunk]) -> bool:
    """Whether the log already carries the run's ``start`` chunk (an earlier attempt got that far)."""
    return any(chunk["type"] == "start" for chunk in chunks)


def has_open_step(chunks: Iterable[UIChunk]) -> bool:
    """Whether the log ends inside a step — a ``start-step`` not closed by ``finish-step`` or ``reset-step``.

    A resumed run emits ``reset-step`` only then: the checkpoint restarts that model step, so the
    client drops its partial parts. A log that ends after ``finish-step`` was lost during a tool
    round; the resumed tools node re-emits the outputs for the same call ids, which must land on
    the tool parts the client already has.
    """
    open_step = False
    for chunk in chunks:
        kind = chunk["type"]
        if kind == "start-step":
            open_step = True
        elif kind in ("finish-step", "reset-step"):
            open_step = False
    return open_step


def finished_steps(chunks: Iterable[UIChunk]) -> int:
    """Model steps an earlier attempt completed (for the run's ``step_count`` on resume)."""
    return sum(1 for chunk in chunks if chunk["type"] == "finish-step")


def sources_of(parts: Iterable[JsonObject]) -> list[Source]:
    """The ``source-url`` parts as :class:`Source`s — what seeds the registry on resume."""
    sources: list[Source] = []
    for part in parts:
        if part.get("type") != "source-url":
            continue
        try:
            source_id = int(str(part.get("sourceId")))
        except ValueError:
            continue
        title = part.get("title")
        sources.append(
            Source(id=source_id, url=str(part.get("url", "")), title=title if isinstance(title, str) else None)
        )
    return sources


def enabled_tools(options: Mapping[str, object]) -> set[str]:
    """The tool names a run's ``options`` switch on (``web_search`` covers search and fetch)."""
    names: set[str] = set()
    if options.get("web_search"):
        names |= WEB_TOOLS
    if options.get("code"):
        names.add(CODE_TOOL)
    return names


async def await_title(task: asyncio.Task[str], *, timeout_s: float) -> str | None:
    """The generated title if it arrives within ``timeout_s`` (``0``: only if already done); else dropped."""
    if task.done():
        return None if task.cancelled() else task.result()
    if timeout_s <= 0:
        task.cancel()
        return None
    try:
        return await asyncio.wait_for(task, timeout_s)
    except TimeoutError:
        return None
