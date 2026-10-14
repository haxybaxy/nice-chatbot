"""The AI SDK *UI Message Stream* vocabulary, and the sink the agent writes it to.

Every chunk the worker produces — and every row in ``run_event`` — is one of the ``TypedDict``s
below, byte-compatible with what ``@ai-sdk/react``'s ``useChat`` consumes
(https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol). Field names are the wire names on purpose,
hence the camelCase keys. Chunks are plain dicts at runtime: ``json.dumps`` them as they are and
never route them through ``BaseSchema`` (its ``str_strip_whitespace`` would eat a ``" world"``
delta).

``UI_CHUNK_ADAPTER`` validates untrusted chunk dicts (replayed rows, custom-stream payloads).
``EventSink`` is the Protocol the agent loop, the tools and the research graph emit through;
``BufferedEventSink`` coalesces consecutive deltas and hands batches to an injected writer (the
worker persists them and notifies the SSE readers). ``CancelToken`` is the cooperative cancel
signal shared by the loop, the tools and the sandbox.
"""

# TypedDict keys are the AI SDK wire names (messageId, toolCallId, ...).

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Literal, NotRequired, Protocol, TypedDict

from pydantic import Discriminator, Tag, TypeAdapter

type JsonObject = dict[str, object]

# ── Chunks ───────────────────────────────────────────────────────────────────


class StartChunk(TypedDict):
    type: Literal["start"]
    messageId: NotRequired[str]


class StartStepChunk(TypedDict):
    type: Literal["start-step"]


class FinishStepChunk(TypedDict):
    type: Literal["finish-step"]


class ResetStepChunk(TypedDict):
    """Discard the parts received since the latest ``start-step`` (a retried step after a resume)."""

    type: Literal["reset-step"]


class TextStartChunk(TypedDict):
    type: Literal["text-start"]
    id: str


class TextDeltaChunk(TypedDict):
    type: Literal["text-delta"]
    id: str
    delta: str


class TextEndChunk(TypedDict):
    type: Literal["text-end"]
    id: str


class ReasoningStartChunk(TypedDict):
    type: Literal["reasoning-start"]
    id: str


class ReasoningDeltaChunk(TypedDict):
    type: Literal["reasoning-delta"]
    id: str
    delta: str


class ReasoningEndChunk(TypedDict):
    type: Literal["reasoning-end"]
    id: str


class SourceUrlChunk(TypedDict):
    type: Literal["source-url"]
    sourceId: str
    url: str
    title: NotRequired[str]


class ToolInputStartChunk(TypedDict):
    type: Literal["tool-input-start"]
    toolCallId: str
    toolName: str


class ToolInputDeltaChunk(TypedDict):
    type: Literal["tool-input-delta"]
    toolCallId: str
    inputTextDelta: str


class ToolInputAvailableChunk(TypedDict):
    type: Literal["tool-input-available"]
    toolCallId: str
    toolName: str
    input: object


class ToolOutputAvailableChunk(TypedDict):
    type: Literal["tool-output-available"]
    toolCallId: str
    output: object


class ToolOutputErrorChunk(TypedDict):
    type: Literal["tool-output-error"]
    toolCallId: str
    errorText: str


class DataChunk(TypedDict):
    """``data-<name>``: a typed side channel. With ``id`` the client replaces the part in place;
    with ``transient`` it is delivered to ``onData`` only and never becomes a part."""

    type: str
    data: object
    id: NotRequired[str]
    transient: NotRequired[bool]


class FinishChunk(TypedDict):
    type: Literal["finish"]
    finishReason: NotRequired[str]


class ErrorChunk(TypedDict):
    type: Literal["error"]
    errorText: str


class AbortChunk(TypedDict):
    type: Literal["abort"]
    reason: NotRequired[str]


DATA_PREFIX = "data-"
TOOL_PREFIX = "tool-"


def _chunk_tag(value: object) -> str | None:
    """Discriminator: the chunk type, with every ``data-*`` collapsing to ``"data"``."""
    if isinstance(value, dict):
        chunk_type = value.get("type")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(chunk_type, str):
            return "data" if chunk_type.startswith(DATA_PREFIX) else chunk_type
    return None


type UIChunk = Annotated[
    Annotated[StartChunk, Tag("start")]
    | Annotated[StartStepChunk, Tag("start-step")]
    | Annotated[FinishStepChunk, Tag("finish-step")]
    | Annotated[ResetStepChunk, Tag("reset-step")]
    | Annotated[TextStartChunk, Tag("text-start")]
    | Annotated[TextDeltaChunk, Tag("text-delta")]
    | Annotated[TextEndChunk, Tag("text-end")]
    | Annotated[ReasoningStartChunk, Tag("reasoning-start")]
    | Annotated[ReasoningDeltaChunk, Tag("reasoning-delta")]
    | Annotated[ReasoningEndChunk, Tag("reasoning-end")]
    | Annotated[SourceUrlChunk, Tag("source-url")]
    | Annotated[ToolInputStartChunk, Tag("tool-input-start")]
    | Annotated[ToolInputDeltaChunk, Tag("tool-input-delta")]
    | Annotated[ToolInputAvailableChunk, Tag("tool-input-available")]
    | Annotated[ToolOutputAvailableChunk, Tag("tool-output-available")]
    | Annotated[ToolOutputErrorChunk, Tag("tool-output-error")]
    | Annotated[DataChunk, Tag("data")]
    | Annotated[FinishChunk, Tag("finish")]
    | Annotated[ErrorChunk, Tag("error")]
    | Annotated[AbortChunk, Tag("abort")],
    Discriminator(_chunk_tag),
]

UI_CHUNK_ADAPTER: TypeAdapter[UIChunk] = TypeAdapter(UIChunk)

# A stream ends with exactly one of these; the SSE reader closes after it.
TERMINAL_CHUNK_TYPES: frozenset[str] = frozenset({"finish", "error", "abort"})
# Consecutive chunks of these types with the same id are merged by the buffered sink.
_DELTA_KEYS: dict[str, tuple[str, str]] = {
    "text-delta": ("id", "delta"),
    "reasoning-delta": ("id", "delta"),
    "tool-input-delta": ("toolCallId", "inputTextDelta"),
}


def is_terminal(chunk: UIChunk) -> bool:
    return chunk["type"] in TERMINAL_CHUNK_TYPES


def data_chunk(name: str, data: object, *, id: str | None = None, transient: bool = False) -> DataChunk:
    """A ``data-<name>`` chunk; ``id`` makes later chunks with the same id replace it in the UI."""
    chunk: DataChunk = {"type": f"{DATA_PREFIX}{name}", "data": data}
    if id is not None:
        chunk["id"] = id
    if transient:
        chunk["transient"] = True
    return chunk


def source_url_chunk(source_id: str, url: str, title: str | None = None) -> SourceUrlChunk:
    chunk: SourceUrlChunk = {"type": "source-url", "sourceId": source_id, "url": url}
    if title:
        chunk["title"] = title
    return chunk


# ── Sink ─────────────────────────────────────────────────────────────────────


class EventSink(Protocol):
    """Where a run's chunks go, in order. ``flush`` forces buffered deltas out (step boundaries)."""

    async def emit(self, chunk: UIChunk) -> None: ...
    async def flush(self) -> None: ...


class CancelToken:
    """Cooperative cancellation shared by the loop, the tools and the sandbox."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self.reason: str | None = None

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def request(self, reason: str = "cancelled") -> None:
        if not self._event.is_set():
            self.reason = reason
            self._event.set()

    async def wait(self) -> str:
        await self._event.wait()
        return self.reason or "cancelled"


type FlushFn = Callable[[Sequence[UIChunk]], Awaitable[None]]


class BufferedEventSink:
    """Coalesces consecutive deltas and writes batches through ``flush_fn``.

    A batch is written when it holds ``max_buffered`` chunks, when ``flush_interval_ms`` has
    passed since its first chunk (a timer fires even if no further chunk arrives), when a
    terminal chunk is emitted, or on an explicit ``flush()``. Writes are serialized so batches
    never interleave — the writer assigns consecutive sequence numbers.
    """

    def __init__(
        self,
        flush_fn: FlushFn,
        *,
        flush_interval_ms: int = 75,
        max_buffered: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._flush_fn = flush_fn
        self._interval_s = flush_interval_ms / 1000
        self._max = max_buffered
        self._clock = clock
        self._buffer: list[UIChunk] = []
        self._first_at: float | None = None
        self._lock = asyncio.Lock()
        self._timer: asyncio.TimerHandle | None = None
        # Timer-started flush tasks, referenced until done so the loop does not drop them.
        self._timer_tasks: set[asyncio.Task[None]] = set()

    async def emit(self, chunk: UIChunk) -> None:
        if not self._coalesce(chunk):
            self._buffer.append(chunk)
        now = self._clock()
        if self._first_at is None:
            self._first_at = now
            self._arm_timer()
        due = len(self._buffer) >= self._max or now - self._first_at >= self._interval_s
        if due or is_terminal(chunk):
            await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            self._disarm_timer()
            if not self._buffer:
                return
            batch = self._buffer
            self._buffer = []
            self._first_at = None
            await self._flush_fn(batch)

    def _coalesce(self, chunk: UIChunk) -> bool:
        keys = _DELTA_KEYS.get(chunk["type"])
        if keys is None or not self._buffer:
            return False
        last = self._buffer[-1]
        id_key, delta_key = keys
        if last["type"] != chunk["type"] or last.get(id_key) != chunk.get(id_key):
            return False
        merged = dict(last)
        merged[delta_key] = str(last.get(delta_key, "")) + str(chunk.get(delta_key, ""))
        self._buffer[-1] = UI_CHUNK_ADAPTER.validate_python(merged)
        return True

    def _arm_timer(self) -> None:
        loop = asyncio.get_running_loop()
        self._timer = loop.call_later(self._interval_s, self._on_timer)

    def _on_timer(self) -> None:
        self._timer = None
        task = asyncio.get_running_loop().create_task(self.flush())
        self._timer_tasks.add(task)
        task.add_done_callback(self._timer_tasks.discard)

    def _disarm_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
