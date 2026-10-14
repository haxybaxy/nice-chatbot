"""The tool framework's vocabulary: run context, sources, budgets and the tool definition.

A tool is a :class:`Tool` — a name, a description the model reads, a ``BaseSchema`` for its
arguments and an async ``run`` that receives the validated arguments plus the
:class:`ToolCallContext` (the run's :class:`RunContext`, the tool call id and the stream writer
for progress / source chunks). ``registry.py`` turns these into LangChain ``StructuredTool``s per
run.

:class:`RunContext` is LangGraph's ``context_schema``: everything a run needs that must *not* be
checkpointed — the cancel token, the live clients, the tracer, the source numbering and the tool
budget. On a resumed run the worker rebuilds it and seeds the sources from the persisted
``source-url`` parts, so ``[n]`` numbering stays stable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from app.core.observability import Tracer
from app.core.sandbox import SandboxClient
from app.core.schemas import BaseSchema
from app.core.search import SearchClient
from app.core.ui_stream import CancelToken, JsonObject, UIChunk

type Capability = Literal["search", "sandbox"]
type ChunkWriter = Callable[[UIChunk], None]
# JSON Schema keywords the model does not need (validation stays in pydantic) and that strict tool
# schemas on some providers reject outright.
_SCHEMA_NOISE = frozenset(
    {
        "title",
        "default",
        "maxLength",
        "minLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "maxItems",
        "minItems",
    }
)


class ToolInputError(ValueError):
    """The model's arguments did not validate; the message goes back to the model as the tool result."""


# ── Sources ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Source:
    id: int
    url: str
    title: str | None


def normalize_url(url: str) -> str:
    """Dedupe key for sources: scheme/host lower-cased, fragment and trailing slash dropped."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


class SourceRegistry:
    """Run-global ``[n]`` numbering, one number per distinct URL."""

    def __init__(self) -> None:
        self._by_key: dict[str, Source] = {}
        self._order: list[Source] = []

    def add(self, url: str, title: str | None = None) -> tuple[Source, bool]:
        """Register ``url``; returns the source and whether it is new (→ emit ``source-url`` once)."""
        key = normalize_url(url)
        existing = self._by_key.get(key)
        if existing is not None:
            return existing, False
        source = Source(id=len(self._order) + 1, url=url, title=title or None)
        self._by_key[key] = source
        self._order.append(source)
        return source, True

    def seed(self, sources: Iterable[Source]) -> None:
        """Restore numbering from persisted sources (resume); ids must be the persisted ones."""
        for source in sorted(sources, key=lambda item: item.id):
            key = normalize_url(source.url)
            if key not in self._by_key:
                self._by_key[key] = source
                self._order.append(source)

    def get(self, source_id: int) -> Source | None:
        return next((source for source in self._order if source.id == source_id), None)

    def all(self) -> list[Source]:
        return list(self._order)

    def __len__(self) -> int:
        return len(self._order)


# ── Budgets ──────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class ToolBudget:
    """How many tool calls a run may make and how much of each result the model sees."""

    max_tool_calls: int
    calls_made: int = 0
    max_output_chars: int = 12_000

    @property
    def exhausted(self) -> bool:
        return self.calls_made >= self.max_tool_calls

    def take(self) -> bool:
        """Consume one call; ``False`` when the budget is already spent."""
        if self.exhausted:
            return False
        self.calls_made += 1
        return True


@dataclass(slots=True)
class TokenBudget:
    """Total tokens a deep-research run may spend across its subagents."""

    limit: int
    spent: int = 0

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit

    def spend(self, tokens: int) -> None:
        self.spent += max(0, tokens)


# ── Run context ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class RunContext:
    """Per-run dependencies and state handed to every node and tool (never checkpointed)."""

    run_id: UUID
    conversation_id: UUID
    user_id: UUID
    team_id: UUID
    attempt: int
    cancel: CancelToken
    tracer: Tracer
    budget: ToolBudget
    search: SearchClient | None = None
    sandbox: SandboxClient | None = None
    sources: SourceRegistry = field(default_factory=SourceRegistry)
    # Deep research only.
    research_semaphore: asyncio.Semaphore | None = None
    token_budget: TokenBudget | None = None


# ── Tool definition ──────────────────────────────────────────────────────────


class ToolArtifact(TypedDict):
    """The ``artifact`` half of a tool result: what the UI renders (wire camelCase) and whether it is an error."""

    output: JsonObject
    is_error: bool


@dataclass(frozen=True, slots=True)
class ToolResult:
    content: str  # what the model reads
    output: JsonObject  # what the UI renders (`tool-output-available.output`)
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ToolCallContext:
    ctx: RunContext
    tool_call_id: str
    write: ChunkWriter


class ToolSpec(Protocol):
    """What the registry needs from a tool, independent of its argument type."""

    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def requires(self) -> Capability | None: ...
    def json_schema(self) -> JsonObject: ...
    async def invoke(self, call: ToolCallContext, arguments: Mapping[str, object]) -> ToolResult: ...


def sanitize_schema(schema: object) -> object:
    """Strip pydantic's titles, defaults and bounds from a JSON schema (recursively)."""
    if isinstance(schema, dict):
        items: list[tuple[object, object]] = list(schema.items())  # pyright: ignore[reportUnknownArgumentType] — JSON
        return {str(key): sanitize_schema(value) for key, value in items if key not in _SCHEMA_NOISE}
    if isinstance(schema, list):
        values: list[object] = list(schema)  # pyright: ignore[reportUnknownArgumentType] — JSON
        return [sanitize_schema(value) for value in values]
    return schema


class Tool[TIn: BaseSchema]:
    """A built-in tool: validated ``TIn`` in, :class:`ToolResult` out."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        args_schema: type[TIn],
        requires: Capability | None,
        run: Callable[[ToolCallContext, TIn], Awaitable[ToolResult]],
    ) -> None:
        self._name = name
        self._description = description
        self._args_schema = args_schema
        self._requires: Capability | None = requires
        self._run = run

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def requires(self) -> Capability | None:
        return self._requires

    def json_schema(self) -> JsonObject:
        """The model-facing argument schema: snake_case names, no titles/defaults/bounds."""
        schema = sanitize_schema(self._args_schema.model_json_schema(by_alias=False))
        return schema if isinstance(schema, dict) else {}  # pyright: ignore[reportUnknownVariableType] — JSON object

    async def invoke(self, call: ToolCallContext, arguments: Mapping[str, object]) -> ToolResult:
        parsed = self._args_schema.model_validate(dict(arguments))
        return await self._run(call, parsed)
