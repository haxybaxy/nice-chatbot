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

# Library boundary: LangGraph's v2 stream events are `dict[str, Any]`; message content is loosely typed.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from pydantic import ValidationError

from app.core.agent.state import StopInfo
from app.core.exceptions import AppError
from app.core.llm.errors import to_app_error
from app.core.logging_config import get_logger
from app.core.tools.base import RunContext
from app.core.ui_fold import fold_parts
from app.core.ui_stream import UI_CHUNK_ADAPTER, JsonObject, UIChunk

logger = get_logger(__name__)

DEFAULT_STREAMED_NODES: frozenset[str] = frozenset({"agent", "synthesize"})
TOOL_NODES: frozenset[str] = frozenset({"tools", "budget_exceeded"})
_DONE = object()


# ── Usage ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def __add__(self, other: UsageTotals) -> UsageTotals:
        return UsageTotals(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def usage_of(message: AIMessage) -> UsageTotals:
    """The usage a provider reported on ``message`` (zeros when it reported none)."""
    usage = message.usage_metadata
    if usage is None:
        return UsageTotals()
    details = usage.get("input_token_details") or {}
    return UsageTotals(
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_read_tokens=details.get("cache_read", 0),
        cache_creation_tokens=details.get("cache_creation", 0),
    )


def model_name_of(message: AIMessage) -> str:
    name = message.response_metadata.get("model_name") or message.response_metadata.get("model")
    return name if isinstance(name, str) and name else "unknown"


@dataclass(frozen=True, slots=True)
class RunUsage:
    total: UsageTotals = UsageTotals()
    by_model: Mapping[str, UsageTotals] = field(default_factory=dict)

    def add(self, model: str, usage: UsageTotals) -> RunUsage:
        by_model = dict(self.by_model)
        by_model[model] = by_model.get(model, UsageTotals()) + usage
        return RunUsage(total=self.total + usage, by_model=by_model)


# ── Events ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class UIChunkEvent:
    chunk: UIChunk


@dataclass(frozen=True, slots=True)
class StepCompleted:
    kind: Literal["assistant", "tool"]
    # The LangChain messages this step added (append to `provider_messages` via `dump_turn`).
    messages: Sequence[BaseMessage]
    # Every UI part of the assistant message so far (persist as `message.parts`).
    parts: Sequence[JsonObject]
    usage: RunUsage
    step: int


@dataclass(frozen=True, slots=True)
class RunFinished:
    stop: StopInfo
    usage: RunUsage
    parts: Sequence[JsonObject]
    error: AppError | None = None

    @property
    def finish_reason(self) -> str:
        return self.stop.finish_reason


type MappedEvent = UIChunkEvent | StepCompleted | RunFinished


# ── Content helpers ──────────────────────────────────────────────────────────


def _blocks(content: object) -> Iterable[tuple[Literal["text", "reasoning"], str]]:
    """Text and reasoning fragments of a message's content, in order (tool blocks are skipped)."""
    if isinstance(content, str):
        if content:
            yield "text", content
        return
    if not isinstance(content, list):
        return
    for block in cast("list[object]", content):
        if isinstance(block, str):
            if block:
                yield "text", block
            continue
        if not isinstance(block, Mapping):
            continue
        item = cast("Mapping[str, object]", block)
        kind = item.get("type")
        if kind == "text":
            text = item.get("text")
            if isinstance(text, str) and text:
                yield "text", text
        elif kind in ("reasoning", "thinking"):
            text = item.get("reasoning") if kind == "reasoning" else item.get("thinking")
            if isinstance(text, str) and text:
                yield "reasoning", text


def _text_of(message: BaseMessage) -> str:
    return "".join(text for kind, text in _blocks(message.content) if kind == "text")


def _tool_messages(update: Mapping[str, object]) -> list[ToolMessage]:
    messages = update.get("messages")
    if not isinstance(messages, list):
        return []
    return [message for message in cast("list[object]", messages) if isinstance(message, ToolMessage)]


def _ai_messages(update: Mapping[str, object]) -> list[AIMessage]:
    messages = update.get("messages")
    if not isinstance(messages, list):
        return []
    return [message for message in cast("list[object]", messages) if isinstance(message, AIMessage)]


# ── Mapper ───────────────────────────────────────────────────────────────────


class _Mapper:
    def __init__(self, streamed_nodes: Collection[str]) -> None:
        self._streamed_nodes = set(streamed_nodes)
        self.chunks: list[UIChunk] = []
        self.usage = RunUsage()
        self.last_stop: StopInfo | None = None
        self._step_open = False
        self._streamed_in_step = False
        self._steps_done = 0
        self._text_id: str | None = None
        self._reasoning_id: str | None = None
        self._calls_by_index: dict[int, str] = {}
        self._started_calls: set[str] = set()

    # chunk emission

    def _emit(self, chunk: UIChunk) -> UIChunkEvent:
        self.chunks.append(chunk)
        return UIChunkEvent(chunk)

    def parts(self) -> list[JsonObject]:
        return fold_parts(self.chunks)

    def _open_step(self) -> list[UIChunkEvent]:
        self._step_open = True
        self._streamed_in_step = False
        self._calls_by_index.clear()
        return [self._emit({"type": "start-step"})]

    def _close_text(self) -> list[UIChunkEvent]:
        out: list[UIChunkEvent] = []
        if self._text_id is not None:
            out.append(self._emit({"type": "text-end", "id": self._text_id}))
            self._text_id = None
        if self._reasoning_id is not None:
            out.append(self._emit({"type": "reasoning-end", "id": self._reasoning_id}))
            self._reasoning_id = None
        return out

    def _delta(self, kind: Literal["text", "reasoning"], text: str) -> list[UIChunkEvent]:
        out: list[UIChunkEvent] = []
        if kind == "text":
            if self._text_id is None:
                out.extend(self._close_text())
                self._text_id = uuid.uuid4().hex
                out.append(self._emit({"type": "text-start", "id": self._text_id}))
            out.append(self._emit({"type": "text-delta", "id": self._text_id, "delta": text}))
        else:
            if self._reasoning_id is None:
                out.extend(self._close_text())
                self._reasoning_id = uuid.uuid4().hex
                out.append(self._emit({"type": "reasoning-start", "id": self._reasoning_id}))
            out.append(self._emit({"type": "reasoning-delta", "id": self._reasoning_id, "delta": text}))
        return out

    def _tool_start(self, call_id: str, name: str) -> list[UIChunkEvent]:
        out = self._close_text()
        self._started_calls.add(call_id)
        out.append(self._emit({"type": "tool-input-start", "toolCallId": call_id, "toolName": name}))
        return out

    def _finish_step(self) -> list[UIChunkEvent]:
        out = self._close_text()
        if self._step_open:
            out.append(self._emit({"type": "finish-step"}))
            self._step_open = False
        return out

    # graph events

    def on_message_chunk(self, message: object, node: str) -> list[UIChunkEvent]:
        if node not in self._streamed_nodes or not isinstance(message, AIMessageChunk):
            return []
        out: list[UIChunkEvent] = []
        if not self._step_open:
            out.extend(self._open_step())
        self._streamed_in_step = True
        for kind, text in _blocks(message.content):
            out.extend(self._delta(kind, text))
        for call in message.tool_call_chunks:
            call_id = call.get("id")
            index = call.get("index")
            if call_id and call_id not in self._started_calls:
                out.extend(self._tool_start(call_id, call.get("name") or "unknown"))
                if isinstance(index, int):
                    self._calls_by_index[index] = call_id
            resolved = call_id or (self._calls_by_index.get(index) if isinstance(index, int) else None)
            args = call.get("args")
            if resolved and args:
                out.append(self._emit({"type": "tool-input-delta", "toolCallId": resolved, "inputTextDelta": args}))
        return out

    def on_model_update(self, update: Mapping[str, object]) -> tuple[list[UIChunkEvent], StepCompleted | None]:
        stop = update.get("stop")
        if isinstance(stop, StopInfo):
            self.last_stop = stop
        messages = _ai_messages(update)
        if not messages:
            return [], None
        out: list[UIChunkEvent] = []
        for message in messages:
            if not self._step_open:
                out.extend(self._open_step())
            if not self._streamed_in_step:  # `nostream` model, or a provider that did not stream
                for kind, text in _blocks(message.content):
                    out.extend(self._delta(kind, text))
            out.extend(self._close_text())
            for call in message.tool_calls:
                call_id = str(call.get("id") or uuid.uuid4().hex)
                if call_id not in self._started_calls:
                    out.extend(self._tool_start(call_id, call["name"]))
                out.append(
                    self._emit(
                        {
                            "type": "tool-input-available",
                            "toolCallId": call_id,
                            "toolName": call["name"],
                            "input": call["args"],
                        }
                    )
                )
            self.usage = self.usage.add(model_name_of(message), usage_of(message))
        out.extend(self._finish_step())
        self._steps_done += 1
        step = StepCompleted(
            kind="assistant", messages=list(messages), parts=self.parts(), usage=self.usage, step=self._steps_done
        )
        return out, step

    def on_tool_update(self, update: Mapping[str, object]) -> tuple[list[UIChunkEvent], StepCompleted | None]:
        messages = _tool_messages(update)
        if not messages:
            return [], None
        out: list[UIChunkEvent] = []
        for message in messages:
            artifact = message.artifact if isinstance(message.artifact, Mapping) else None
            artifact_map = cast("Mapping[str, object] | None", artifact)
            is_error = message.status == "error" or bool(artifact_map and artifact_map.get("is_error"))
            if is_error:
                out.append(
                    self._emit(
                        {
                            "type": "tool-output-error",
                            "toolCallId": message.tool_call_id,
                            "errorText": _text_of(message),
                        }
                    )
                )
                continue
            output = artifact_map.get("output") if artifact_map is not None else None
            if output is None:
                output = {"content": _text_of(message)}
            out.append(
                self._emit({"type": "tool-output-available", "toolCallId": message.tool_call_id, "output": output})
            )
        self._steps_done += 1
        step = StepCompleted(
            kind="tool", messages=list(messages), parts=self.parts(), usage=self.usage, step=self._steps_done
        )
        return out, step

    def on_custom(self, data: object) -> list[UIChunkEvent]:
        try:
            chunk = UI_CHUNK_ADAPTER.validate_python(data)
        except ValidationError:
            logger.warning("ignoring invalid custom stream chunk", chunk_type=type(data).__name__)
            return []
        return [self._emit(chunk)]

    def handle(self, event: Mapping[str, object]) -> list[MappedEvent]:
        kind = event.get("type")
        namespace = event.get("ns")
        data = event.get("data")
        if kind == "custom":
            return list(self.on_custom(data))
        if namespace:  # a nested graph (research subagent): its node reports progress itself
            return []
        if kind == "messages" and isinstance(data, tuple) and len(cast("tuple[object, ...]", data)) == 2:
            message, metadata = cast("tuple[object, object]", data)
            node = metadata.get("langgraph_node") if isinstance(metadata, Mapping) else None
            return list(self.on_message_chunk(message, str(node)))
        if kind == "updates" and isinstance(data, Mapping):
            out: list[MappedEvent] = []
            for node, update in cast("Mapping[str, object]", data).items():
                if not isinstance(update, Mapping):
                    continue
                update_map = cast("Mapping[str, object]", update)
                if node in TOOL_NODES:
                    chunks, step = self.on_tool_update(update_map)
                elif node in self._streamed_nodes:
                    chunks, step = self.on_model_update(update_map)
                else:
                    stop = update_map.get("stop")
                    if isinstance(stop, StopInfo):
                        self.last_stop = stop
                    continue
                out.extend(chunks)
                if step is not None:
                    out.append(step)
            return out
        return []

    def finish(self, *, cancelled: bool = False, error: AppError | None = None) -> list[MappedEvent]:
        out: list[MappedEvent] = list(self._finish_step())
        if cancelled:
            stop = StopInfo("cancelled")
            out.append(self._emit({"type": "abort", "reason": "cancelled"}))
        elif error is not None:
            stop = StopInfo("error", explanation=error.message)
            out.append(self._emit({"type": "error", "errorText": error.message}))
        else:
            stop = self.last_stop or StopInfo("end")
            if stop.reason == "error":
                out.append(self._emit({"type": "error", "errorText": stop.explanation or "The assistant failed"}))
            else:
                out.append(self._emit({"type": "finish", "finishReason": stop.finish_reason}))
        out.append(RunFinished(stop=stop, usage=self.usage, parts=self.parts(), error=error))
        return out


async def _next(events: AsyncIterator[object]) -> object:
    try:
        return await anext(events)
    except StopAsyncIteration:
        return _DONE


async def map_graph_stream(
    events: AsyncIterator[object],
    *,
    ctx: RunContext,
    streamed_nodes: Collection[str] = DEFAULT_STREAMED_NODES,
) -> AsyncGenerator[MappedEvent]:
    """Turn a v2 LangGraph stream into UI chunks, step completions and one ``RunFinished``."""
    mapper = _Mapper(streamed_nodes)
    cancel_task: asyncio.Task[str] = asyncio.ensure_future(ctx.cancel.wait())
    next_task: asyncio.Task[object] | None = None
    try:
        while True:
            next_task = asyncio.ensure_future(_next(events))
            done, _ = await asyncio.wait({next_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
            if next_task not in done:
                next_task.cancel()
                await asyncio.gather(next_task, return_exceptions=True)
                if isinstance(events, AsyncGenerator):
                    await events.aclose()
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
        if ctx.cancel.requested and mapper.last_stop is not None and mapper.last_stop.reason == "cancelled":
            for item in mapper.finish(cancelled=True):
                yield item
            return
        for item in mapper.finish():
            yield item
    except Exception as error:  # noqa: BLE001 — every failure must end the stream with an `error` chunk
        app_error = to_app_error(error) or AppError.internal("The assistant failed unexpectedly", cause=error)
        logger.error("graph stream failed", error=str(app_error), cause=repr(error))
        for item in mapper.finish(error=app_error):
            yield item
    finally:
        cancel_task.cancel()
        if next_task is not None and not next_task.done():
            next_task.cancel()
