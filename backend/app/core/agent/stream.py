"""Map a LangGraph stream onto the UI Message Stream, one chunk at a time.

``map_graph_stream`` consumes ``graph.astream(..., stream_mode=["messages", "updates", "custom"],
version="v2", subgraphs=True)`` and yields three kinds of events:

* ``UIChunkEvent`` — a wire chunk for the sink (``start-step``, text/reasoning/tool-input deltas
  while the model streams, ``tool-input-available`` + ``finish-step`` when its message lands,
  ``tool-output-*`` when the tools node lands, pass-through of the tools' ``custom`` chunks,
  and the terminal ``finish`` / ``error`` / ``abort``);
* ``StepCompleted`` — after every model or tool step: the step's new LangChain messages (for
  ``provider_messages``), every part so far (``fold_parts`` of the chunks emitted) and the usage
  so far — everything the worker upserts on the assistant message;
* ``RunFinished`` — once, last: the ``StopInfo``, the total usage, the final parts and the
  ``AppError`` when the graph failed.

Only top-level nodes (``ns == ()``) drive parts: a nested research subagent's own ``messages`` /
``updates`` are reported by its node through ``custom`` chunks instead. Cancellation is a race
against ``ctx.cancel``: when it fires the graph stream is closed (LangGraph cancels the in-flight
node) and the run ends with ``abort``.
"""

# Library boundary: LangGraph's v2 stream events are `dict[str, Any]`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Collection, Mapping
from typing import cast

from app.core.agent.events import MappedEvent, RunFinished, StepCompleted, UIChunkEvent
from app.core.agent.mapper import DEFAULT_STREAMED_NODES, Mapper
from app.core.agent.usage import UsageTotals
from app.core.exceptions import AppError
from app.core.llm.errors import to_app_error
from app.core.logging_config import get_logger
from app.core.tools.base import RunContext

__all__ = ["DEFAULT_STREAMED_NODES", "RunFinished", "StepCompleted", "UIChunkEvent", "UsageTotals", "map_graph_stream"]

logger = get_logger(__name__)
_DONE = object()


async def _next(events: AsyncIterator[object]) -> object:
    try:
        return await anext(events)
    except StopAsyncIteration:
        return _DONE


async def _close(events: AsyncIterator[object]) -> None:
    if isinstance(events, AsyncGenerator):
        await events.aclose()


async def map_graph_stream(
    events: AsyncIterator[object],
    *,
    ctx: RunContext,
    streamed_nodes: Collection[str] = DEFAULT_STREAMED_NODES,
) -> AsyncGenerator[MappedEvent]:
    """Turn a v2 LangGraph stream into UI chunks, step completions and one ``RunFinished``."""
    mapper = Mapper(streamed_nodes, sources=ctx.sources)
    cancel_task: asyncio.Task[str] = asyncio.ensure_future(ctx.cancel.wait())
    next_task: asyncio.Task[object] | None = None
    try:
        while True:
            next_task = asyncio.ensure_future(_next(events))
            done, _ = await asyncio.wait({next_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
            if next_task not in done:
                next_task.cancel()
                await asyncio.gather(next_task, return_exceptions=True)
                await _close(events)
                for item in mapper.finish(cancelled=True):
                    yield item
                return
            event = next_task.result()
            next_task = None
            if event is _DONE:
                break
            if isinstance(event, Mapping):
                for item in mapper.handle(cast("Mapping[str, object]", event)):
                    yield item
        cancelled = mapper.last_stop is not None and mapper.last_stop.reason == "cancelled"
        for item in mapper.finish(cancelled=cancelled):
            yield item
    except Exception as error:  # noqa: BLE001 — every failure must end the stream with an `error` chunk
        app_error = to_app_error(error) or AppError.internal("The assistant failed unexpectedly", cause=error)
        logger.error("graph stream failed", error=str(app_error), cause=repr(error))
        for item in mapper.finish(error=app_error):
            yield item
    finally:
        # The consumer may stop early (wall clock, worker shutdown): settle the pending read, then
        # close the graph stream so LangGraph cancels the node it was running.
        cancel_task.cancel()
        if next_task is not None and not next_task.done():
            next_task.cancel()
            await asyncio.gather(next_task, return_exceptions=True)
        await _close(events)
