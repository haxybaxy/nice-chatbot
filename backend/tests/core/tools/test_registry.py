"""The per-run tool registry: capability filtering, ordering, the model-facing schema, budgets and limits."""

from __future__ import annotations

from dataclasses import replace
from typing import Literal, cast

import pytest
from langchain_core.messages import ToolMessage
from pydantic import Field, ValidationError

from app.core.agent.state import StopInfo
from app.core.exceptions import AppError
from app.core.schemas import BaseSchema
from app.core.tools.base import (
    Source,
    SourceRegistry,
    TokenBudget,
    Tool,
    ToolBudget,
    ToolCallContext,
    ToolInputError,
    ToolResult,
    ToolSpec,
    normalize_url,
    sanitize_schema,
)
from app.core.tools.registry import (
    BUDGET_EXHAUSTED,
    NATIVE_WEB_SEARCH,
    RUN_CANCELLED,
    RunTools,
    ToolRegistry,
    default_tool_registry,
    tool_error_text,
)
from tests.fakes_llm import GPT, LOCAL, OPUS, FakeSandboxClient, FakeSearchClient, make_run_context, scripted_turn
from tests.graph_harness import chat_graph, collect, invoke_state, prompt, scripted_model


class BigIn(BaseSchema):
    text: str = Field(max_length=100_000)
    mode: Literal["short", "long", "cancel"] = "short"


async def _big(call: ToolCallContext, args: BigIn) -> ToolResult:
    if args.mode == "cancel":
        call.ctx.cancel.request("user")
    return ToolResult(content="x" * (5000 if args.mode == "long" else 50), output={"mode": args.mode})


BIG: ToolSpec = Tool(name="big", description="Returns a lot.", args_schema=BigIn, requires=None, run=_big)


ALL_TOOLS = {"web_search", "web_fetch", "run_code"}


class TestForRun:
    def test_filters_by_capability_reports_the_rest_and_sorts_by_name(self) -> None:
        registry = default_tool_registry()
        assert registry.names() == ["run_code", "web_fetch", "web_search"]
        nothing = registry.for_run(make_run_context(), names=ALL_TOOLS, spec=OPUS)
        assert nothing == RunTools(unavailable=("run_code", "web_fetch", "web_search"))
        assert not nothing
        searching = registry.for_run(make_run_context(search=FakeSearchClient()), names=ALL_TOOLS, spec=OPUS)
        assert [tool.name for tool in searching.client] == ["web_fetch", "web_search"]
        assert (searching.names, searching.unavailable, searching.provider) == (("web_fetch", "web_search"), ("run_code",), ())
        everything = registry.for_run(
            make_run_context(search=FakeSearchClient(), sandbox=FakeSandboxClient()), names=ALL_TOOLS, spec=OPUS
        )
        assert [tool.name for tool in everything.client] == ["run_code", "web_fetch", "web_search"]
        assert everything.names == ("run_code", "web_fetch", "web_search")
        assert everything.unavailable == ()
        assert everything.bound == list(everything.client)

    def test_native_search_binds_the_provider_tool_and_covers_web_fetch(self) -> None:
        registry = default_tool_registry()
        # No Tavily client at all: the model's built-in search is enough.
        native = registry.for_run(make_run_context(), names=ALL_TOOLS, spec=GPT)
        assert native.provider == (NATIVE_WEB_SEARCH,)
        assert native.client == ()
        assert (native.names, native.unavailable, native.native_web_search) == (("web_search",), ("run_code",), True)
        assert native.bound == [NATIVE_WEB_SEARCH]
        assert native
        # With Tavily configured too, the built-in search still wins and the sandbox tool joins it.
        both = registry.for_run(
            make_run_context(search=FakeSearchClient(), sandbox=FakeSandboxClient()), names=ALL_TOOLS, spec=GPT
        )
        assert [tool.name for tool in both.client] == ["run_code"]
        assert (both.names, both.provider) == (("run_code", "web_search"), (NATIVE_WEB_SEARCH,))
        # Only web_fetch requested: nothing native about that, so Tavily or nothing.
        fetch_only = registry.for_run(make_run_context(), names={"web_fetch"}, spec=GPT)
        assert fetch_only == RunTools(unavailable=("web_fetch",))

    def test_unknown_names_are_ignored_and_toolless_models_get_nothing(self) -> None:
        ctx = make_run_context(search=FakeSearchClient())
        assert default_tool_registry().for_run(ctx, names={"web_search", "bogus"}, spec=OPUS).names == ("web_search",)
        toolless = replace(LOCAL, supports_tools=False)
        assert default_tool_registry().for_run(ctx, names={"web_search", "bogus"}, spec=toolless) == RunTools(
            unavailable=("web_search",)
        )

    def test_configured_names_follow_the_server_capabilities(self) -> None:
        registry = default_tool_registry()
        assert registry.configured(search=False, sandbox=False, native_web_search=False) == []
        assert registry.configured(search=False, sandbox=False, native_web_search=True) == ["web_search"]
        assert registry.configured(search=True, sandbox=True, native_web_search=False) == [
            "run_code",
            "web_fetch",
            "web_search",
        ]

    def test_structured_tool_carries_sanitized_schema_and_eager_streaming(self) -> None:
        ctx = make_run_context(search=FakeSearchClient())
        (tool,) = default_tool_registry().for_run(ctx, names={"web_search"}, spec=OPUS).client
        assert tool.name == "web_search"
        assert tool.response_format == "content_and_artifact"
        assert tool.extras == {"eager_input_streaming": True}
        schema = tool.args_schema
        assert isinstance(schema, dict)
        properties = schema["properties"]
        assert set(properties) == {"query", "max_results", "topic", "recency", "include_domains"}
        assert "maxLength" not in properties["query"]
        assert "default" not in properties["max_results"]
        assert "title" not in properties["query"]
        assert "description" in properties["query"]
        assert properties["topic"]["enum"] == ["general", "news", "finance"]
        assert schema["required"] == ["query"]


class TestClosure:
    async def test_output_is_truncated_to_the_budget(self) -> None:
        ctx = make_run_context(max_output_chars=200)
        tools = ToolRegistry([BIG]).for_run(ctx, names={"big"}, spec=OPUS)
        turn = scripted_turn(tool_calls=[("big", {"text": "t", "mode": "long"})])
        model, built = scripted_model([turn, scripted_turn("ok")])
        await collect(chat_graph(built, tools), ctx, prompt())
        tool_message = model.calls[1][-1]
        assert len(str(tool_message.content)) <= 200
        assert str(tool_message.content).endswith("[output truncated]")

    async def test_budget_exhaustion_is_a_soft_error(self) -> None:
        ctx = make_run_context(max_tool_calls=1)
        tools = ToolRegistry([BIG]).for_run(ctx, names={"big"}, spec=OPUS)
        turn = scripted_turn(tool_calls=[("big", {"text": "a"}), ("big", {"text": "b"})])
        model, built = scripted_model([turn, scripted_turn("ok")])
        result = await collect(chat_graph(built, tools), ctx, prompt())
        contents = sorted(str(message.content) for message in model.calls[1][-2:])
        assert contents[0] == BUDGET_EXHAUSTED
        assert len(result.of_type("tool-output-error")) == 1
        assert len(result.of_type("tool-output-available")) == 1
        assert ctx.budget.calls_made == 1

    async def test_cancelled_run_refuses_tool_calls(self) -> None:
        ctx = make_run_context()
        tools = ToolRegistry([BIG]).for_run(ctx, names={"big"}, spec=OPUS)
        # The first call requests cancellation while running; the second (same step) is refused,
        # and the agent node then stops without another model call.
        turn = scripted_turn(tool_calls=[("big", {"text": "a", "mode": "cancel"}), ("big", {"text": "b"})])
        model, built = scripted_model([turn, scripted_turn("never")])
        state = await invoke_state(chat_graph(built, tools), ctx, prompt())
        results = [message for message in cast("list[object]", state["messages"]) if isinstance(message, ToolMessage)]
        assert [str(message.content) for message in results][1] == RUN_CANCELLED
        assert results[1].artifact == {"output": {"error": "cancelled"}, "is_error": True}
        assert ctx.budget.calls_made == 1
        assert state["stop"] == StopInfo("cancelled")
        assert len(model.calls) == 1

        # Through the mapper the same run ends with `abort` as soon as the cancel is seen.
        ctx = make_run_context()
        tools = ToolRegistry([BIG]).for_run(ctx, names={"big"}, spec=OPUS)
        _, built = scripted_model([turn, scripted_turn("never")])
        result = await collect(chat_graph(built, tools), ctx, prompt())
        assert result.finished.stop.reason == "cancelled"
        assert result.types[-1] == "abort"


class TestErrorText:
    def test_messages_for_each_failure_kind(self) -> None:
        assert tool_error_text(ToolInputError("Invalid arguments for x: y")) == "Invalid arguments for x: y"
        assert (
            tool_error_text(AppError.service_unavailable("Search provider is busy"))
            == "Tool failed: Search provider is busy"
        )
        assert tool_error_text(RuntimeError("boom")) == "The tool failed unexpectedly. Continue without it."


class TestToolSpec:
    async def test_invoke_validates_then_runs(self) -> None:
        call = ToolCallContext(ctx=make_run_context(), tool_call_id="c1", write=lambda _chunk: None)
        result = await BIG.invoke(call, {"text": "hello"})
        assert result.output == {"mode": "short"}
        with pytest.raises(ValidationError):
            await BIG.invoke(call, {"text": "hello", "mode": "huge"})
        with pytest.raises(ValidationError):
            await BIG.invoke(call, {"nope": 1})

    def test_sanitize_schema_strips_noise_recursively(self) -> None:
        schema = {
            "title": "X",
            "properties": {"a": {"type": "string", "maxLength": 3, "default": "q", "description": "keep"}},
            "items": [{"minimum": 1, "type": "integer"}],
        }
        assert sanitize_schema(schema) == {
            "properties": {"a": {"type": "string", "description": "keep"}},
            "items": [{"type": "integer"}],
        }


class TestSourcesAndBudgets:
    def test_sources_are_numbered_once_per_normalized_url(self) -> None:
        sources = SourceRegistry()
        first, new_1 = sources.add("https://Example.com/a/", "A")
        again, new_2 = sources.add("https://example.com/a#frag")
        second, new_3 = sources.add("https://example.com/b", "B")
        assert (first.id, new_1, again.id, new_2, second.id, new_3) == (1, True, 1, False, 2, True)
        assert sources.get(2) == second
        assert [source.url for source in sources.all()] == ["https://Example.com/a/", "https://example.com/b"]
        assert normalize_url("HTTPS://Example.com/path/?q=1#x") == "https://example.com/path?q=1"

    def test_seed_restores_numbering_on_resume(self) -> None:
        sources = SourceRegistry()
        sources.seed(
            [Source(id=2, url="https://b.example", title="B"), Source(id=1, url="https://a.example", title=None)]
        )
        assert [source.id for source in sources.all()] == [1, 2]
        third, is_new = sources.add("https://c.example")
        assert (third.id, is_new) == (3, True)
        assert sources.add("https://a.example/")[0].id == 1
        assert len(sources) == 3

    def test_budgets(self) -> None:
        budget = ToolBudget(max_tool_calls=2)
        assert budget.take()
        assert budget.take()
        assert not budget.take()
        assert budget.exhausted
        tokens = TokenBudget(limit=100)
        tokens.spend(60)
        assert not tokens.exhausted
        tokens.spend(60)
        assert tokens.exhausted
        assert tokens.spent == 120
