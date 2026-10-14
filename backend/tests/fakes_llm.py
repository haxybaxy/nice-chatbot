"""Offline stand-ins for the LLM layer, the tool clients, the tracer and the event sink.

``ScriptedChatModel`` plays back ``AIMessage`` turns: ``_generate`` returns the next one whole,
``_astream`` cuts it into word-level ``AIMessageChunk``s (text, reasoning, tool-call fragments)
with usage and ``response_metadata`` on the last chunk — the shape ``ChatAnthropic`` /
``ChatOpenAI`` produce, so the graph and the stream mapper are exercised exactly as in production.
``bind_tools`` records the tool names and returns the model itself.
"""

# Library boundary: BaseChatModel's generation hooks and `bind_tools` are typed with `Any`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal, cast
from uuid import UUID, uuid4

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, BaseCallbackHandler, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from pydantic import Field

from app.core.config import Effort
from app.core.exceptions import AppError
from app.core.llm.catalog import ModelCatalog, ModelSpec
from app.core.llm.chat_models import BuiltModel
from app.core.observability import SpanHandle, SpanKind, SpanLevel
from app.core.sandbox import SandboxResult, SandboxRun
from app.core.search import ExtractDepth, ExtractedPage, SearchQuery, SearchResult
from app.core.tools.base import RunContext, ToolBudget
from app.core.ui_stream import CancelToken, JsonObject, UIChunk

_WORDS = re.compile(r"\S+\s*|\s+")

# ── Model specs ──────────────────────────────────────────────────────────────

CATALOG = ModelCatalog(
    model_ids=[
        "anthropic:claude-opus-5-5",
        "anthropic:claude-sonnet-5-5",
        "anthropic:claude-haiku-5-5",
        "openai:llama3.3",
    ],
    default_id="anthropic:claude-opus-5-5",
    title_id="anthropic:claude-haiku-5-5",
    anthropic_configured=True,
    openai_configured=True,
    openai_supports_tools=True,
    openai_supports_reasoning=False,
)
OPUS = CATALOG.get("anthropic:claude-opus-5-5")
SONNET = CATALOG.get("anthropic:claude-sonnet-5-5")
HAIKU = CATALOG.get("anthropic:claude-haiku-5-5")
LOCAL = CATALOG.get("openai:llama3.3")


# ── Scripted turns ───────────────────────────────────────────────────────────


def scripted_turn(
    text: str = "",
    *,
    reasoning: str | None = None,
    tool_calls: Sequence[tuple[str, Mapping[str, object]]] = (),
    stop_reason: str | None = None,
    input_tokens: int = 10,
    output_tokens: int = 5,
    model_name: str = "scripted",
) -> AIMessage:
    """An Anthropic-shaped ``AIMessage``: optional thinking block, text, tool calls, stop reason, usage."""
    content: list[dict[str, object]] = []
    if reasoning:
        content.append({"type": "thinking", "thinking": reasoning, "signature": "sig"})
    if text:
        content.append({"type": "text", "text": text})
    calls: list[dict[str, object]] = []
    for name, args in tool_calls:
        call_id = f"call_{uuid4().hex[:8]}"
        content.append({"type": "tool_use", "id": call_id, "name": name, "input": dict(args)})
        calls.append({"name": name, "args": dict(args), "id": call_id, "type": "tool_call"})
    if stop_reason is None:
        stop_reason = "tool_use" if calls else "end_turn"
    return AIMessage(
        content=cast("list[str | dict[str, object]]", content),
        tool_calls=cast("list[object]", calls),
        response_metadata={"stop_reason": stop_reason, "model_name": model_name, "model_provider": "anthropic"},
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


def _chunks_of(turn: AIMessage) -> list[AIMessageChunk]:
    """Word-level chunks the way a streaming provider emits them."""
    chunks: list[AIMessageChunk] = []
    content = turn.content
    blocks: list[Mapping[str, object]] = []
    if isinstance(content, str):
        if content:
            blocks.append({"type": "text", "text": content})
    else:
        blocks.extend(block for block in cast("list[object]", content) if isinstance(block, Mapping))
    index = 0
    seen_tool_ids: set[str] = set()
    for block in blocks:
        kind = block.get("type")
        if kind == "text":
            for word in _WORDS.findall(str(block.get("text", ""))):
                chunks.append(AIMessageChunk(content=[{"type": "text", "text": word, "index": index}]))
        elif kind == "thinking":
            for word in _WORDS.findall(str(block.get("thinking", ""))):
                chunks.append(AIMessageChunk(content=[{"type": "thinking", "thinking": word, "index": index}]))
            chunks.append(
                AIMessageChunk(content=[{"type": "thinking", "signature": block.get("signature", ""), "index": index}])
            )
        elif kind == "tool_use":
            call_id = str(block.get("id"))
            seen_tool_ids.add(call_id)
            chunks.extend(_tool_call_chunks(call_id, str(block.get("name")), block.get("input"), index))
        index += 1
    for call in turn.tool_calls:
        if call.get("id") in seen_tool_ids:
            continue
        chunks.extend(_tool_call_chunks(str(call.get("id")), call["name"], call["args"], index))
        index += 1
    chunks.append(
        AIMessageChunk(content="", response_metadata=dict(turn.response_metadata), usage_metadata=turn.usage_metadata)
    )
    return chunks


def _tool_call_chunks(call_id: str, name: str, args: object, index: int) -> list[AIMessageChunk]:
    encoded = json.dumps(args, ensure_ascii=False)
    half = max(1, len(encoded) // 2)
    pieces = [encoded[:half], encoded[half:]] if len(encoded) > 1 else [encoded]
    chunks = [
        AIMessageChunk(
            content=[{"type": "tool_use", "id": call_id, "name": name, "input": {}, "index": index}],
            tool_call_chunks=[{"name": name, "args": "", "id": call_id, "index": index}],
        )
    ]
    chunks.extend(
        AIMessageChunk(
            content=[{"type": "input_json_delta", "partial_json": piece, "index": index}],
            tool_call_chunks=[{"name": None, "args": piece, "id": None, "index": index}],
        )
        for piece in pieces
        if piece
    )
    return chunks


class ScriptedChatModel(BaseChatModel):
    """Plays back ``turns`` in order; records every call and every ``bind_tools``."""

    turns: list[AIMessage] = Field(default_factory=list)
    # Exceptions raised instead of a turn, keyed by 0-based call index.
    failures: dict[int, Exception] = Field(default_factory=dict)
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[list[str]] = Field(default_factory=list)
    bind_kwargs: list[dict[str, object]] = Field(default_factory=list)
    invoke_kwargs: list[dict[str, object]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(
        self,
        tools: Sequence[object],
        *,
        tool_choice: object = None,
        **kwargs: object,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        del tool_choice
        self.bound_tools.append([str(getattr(tool, "name", tool)) for tool in tools])
        self.bind_kwargs.append(dict(kwargs))
        return self

    def _next_turn(self, messages: list[BaseMessage], kwargs: Mapping[str, object]) -> AIMessage:
        index = len(self.calls)
        self.calls.append(list(messages))
        self.invoke_kwargs.append({key: value for key, value in kwargs.items() if key not in ("stream", "tools")})
        failure = self.failures.pop(index, None)
        if failure is not None:
            raise failure
        if not self.turns:
            raise RuntimeError("ScriptedChatModel: script exhausted")
        return self.turns.pop(0)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        del stop, run_manager
        return ChatResult(generations=[ChatGeneration(message=self._next_turn(messages, kwargs))])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        del stop
        for chunk in _chunks_of(self._next_turn(messages, kwargs)):
            if run_manager is not None:
                text = chunk.text if isinstance(chunk.content, str) else ""
                await run_manager.on_llm_new_token(text, chunk=ChatGenerationChunk(message=chunk))
            yield ChatGenerationChunk(message=chunk)


@dataclass
class FakeChatModelFactory:
    """``ChatModelFactory`` handing out one scripted model per ``purpose``."""

    by_purpose: dict[str, ScriptedChatModel]
    system_format: Literal["blocks", "text"] = "text"
    builds: list[dict[str, object]] = field(default_factory=list)

    def build(
        self,
        spec: ModelSpec,
        *,
        effort: Effort,
        purpose: str,
        max_tokens: int | None = None,
        output_schema: JsonObject | None = None,
        user_id: UUID | None = None,
        silent: bool = False,
    ) -> BuiltModel:
        self.builds.append(
            {
                "spec": spec.id,
                "effort": effort,
                "purpose": purpose,
                "max_tokens": max_tokens,
                "output_schema": output_schema,
                "user_id": user_id,
                "silent": silent,
            }
        )
        model = self.by_purpose.get(purpose)
        if model is None:
            raise RuntimeError(f"FakeChatModelFactory: no scripted model for purpose {purpose!r}")
        return BuiltModel(
            spec=spec,
            model=model,
            invoke_kwargs={},
            system_format=self.system_format,
            strict_tools=None,
            parallel_tool_calls=None,
        )


# ── Tool clients ─────────────────────────────────────────────────────────────


@dataclass
class FakeSearchClient:
    results: dict[str, list[SearchResult]] = field(default_factory=dict)  # by query
    pages: dict[str, ExtractedPage] = field(default_factory=dict)  # by url
    error: AppError | None = None
    queries: list[SearchQuery] = field(default_factory=list)
    extracts: list[tuple[list[str], str | None, ExtractDepth]] = field(default_factory=list)

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return list(self.results.get(query.query, []))

    async def extract(
        self, urls: Sequence[str], *, query: str | None = None, depth: ExtractDepth = "basic"
    ) -> tuple[list[ExtractedPage], list[str]]:
        self.extracts.append((list(urls), query, depth))
        if self.error is not None:
            raise self.error
        pages = [self.pages[url] for url in urls if url in self.pages]
        failed = [url for url in urls if url not in self.pages]
        return pages, failed


@dataclass
class FakeSandboxClient:
    results: list[SandboxResult] = field(default_factory=list)  # consumed in order; last one repeats
    error: AppError | None = None
    runs: list[SandboxRun] = field(default_factory=list)

    async def run(self, run: SandboxRun, *, cancel: CancelToken | None = None) -> SandboxResult:
        del cancel
        self.runs.append(run)
        if self.error is not None:
            raise self.error
        if not self.results:
            return SandboxResult(stdout="", stderr="", exit_code=0, duration_ms=1, truncated=False, timed_out=False)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


# ── Tracer and sink ──────────────────────────────────────────────────────────


@dataclass
class FakeSpanHandle:
    name: str
    kind: SpanKind
    input: object
    updates: list[dict[str, object]] = field(default_factory=list)

    def update(
        self, *, output: object = None, level: SpanLevel | None = None, status_message: str | None = None
    ) -> None:
        self.updates.append({"output": output, "level": level, "status_message": status_message})


@dataclass
class FakeTracer:
    run_contexts: list[dict[str, object]] = field(default_factory=list)
    spans: list[FakeSpanHandle] = field(default_factory=list)
    handlers: list[BaseCallbackHandler] = field(default_factory=list)
    flushes: int = 0
    shutdowns: int = 0
    trace_id: str | None = "0123456789abcdef0123456789abcdef"

    def callbacks(self) -> list[BaseCallbackHandler]:
        return list(self.handlers)

    @contextmanager
    def run_context(
        self,
        *,
        run_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
        team_id: UUID,
        mode: str,
        model: str,
        attempt: int,
        tags: Sequence[str] = (),
    ) -> Generator[str | None]:
        self.run_contexts.append(
            {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "team_id": team_id,
                "mode": mode,
                "model": model,
                "attempt": attempt,
                "tags": list(tags),
            }
        )
        yield self.trace_id

    @contextmanager
    def span(self, name: str, *, kind: SpanKind = "span", input: object = None) -> Generator[SpanHandle]:
        handle = FakeSpanHandle(name=name, kind=kind, input=input)
        self.spans.append(handle)
        yield handle

    def flush(self) -> None:
        self.flushes += 1

    def shutdown(self) -> None:
        self.shutdowns += 1


@dataclass
class RecordingSink:
    chunks: list[UIChunk] = field(default_factory=list)
    flushes: int = 0

    async def emit(self, chunk: UIChunk) -> None:
        self.chunks.append(chunk)

    async def flush(self) -> None:
        self.flushes += 1

    def types(self) -> list[str]:
        return [chunk["type"] for chunk in self.chunks]


# ── Run context ──────────────────────────────────────────────────────────────


def make_run_context(
    *,
    search: FakeSearchClient | None = None,
    sandbox: FakeSandboxClient | None = None,
    tracer: FakeTracer | None = None,
    max_tool_calls: int = 24,
    max_output_chars: int = 12_000,
    attempt: int = 1,
) -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        user_id=uuid4(),
        team_id=uuid4(),
        attempt=attempt,
        cancel=CancelToken(),
        tracer=tracer or FakeTracer(),
        budget=ToolBudget(max_tool_calls=max_tool_calls, max_output_chars=max_output_chars),
        search=search,
        sandbox=sandbox,
    )
