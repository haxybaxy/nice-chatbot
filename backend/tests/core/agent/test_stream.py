"""The graph → UI Message Stream mapping, chunk by chunk, on the real graph with a scripted model."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from langchain_core.messages import AIMessage, ToolMessage

from app.core.agent.state import AgentLimits
from app.core.tools.base import RunContext
from app.core.ui_fold import fold_parts
from app.core.ui_stream import JsonObject
from tests.core.agent.conftest import chat_graph, collect, echo_tools, prompt, scripted_model
from tests.fakes_llm import scripted_turn


def _tool_part(parts: Sequence[JsonObject], call_id: str) -> JsonObject:
    return next(part for part in parts if part.get("toolCallId") == call_id)


class TestTextAndTools:
    async def test_text_tool_text_produces_the_canonical_chunk_order(self, ctx: RunContext) -> None:
        turn_1 = scripted_turn("Let me check.", reasoning="Need the tool.", tool_calls=[("echo", {"text": "ping"})])
        call_id = str(turn_1.tool_calls[0]["id"])
        _, built = scripted_model([turn_1, scripted_turn("Pong [1].")])
        result = await collect(chat_graph(built, echo_tools(ctx)), ctx, prompt())

        types = result.types
        # Step 1: reasoning, text, streamed tool input, then the settled input and the step end.
        assert types[:4] == ["start-step", "reasoning-start", "reasoning-delta", "reasoning-delta"]
        assert types.index("reasoning-end") < types.index("text-start") < types.index("text-end")
        assert types.index("text-end") < types.index("tool-input-start") < types.index("tool-input-delta")
        assert types.index("tool-input-delta") < types.index("tool-input-available") < types.index("finish-step")
        # Tool round: the transient progress chunk, then the output.
        assert "data-tool-progress" in types
        assert types.index("finish-step") < types.index("tool-output-available")
        # Step 2 and the end of the run.
        assert types.count("start-step") == 2
        assert types[-1] == "finish"
        assert result.chunks[-1] == {"type": "finish", "finishReason": "stop"}

        available = next(chunk for chunk in result.chunks if chunk["type"] == "tool-input-available")
        assert available == {
            "type": "tool-input-available",
            "toolCallId": call_id,
            "toolName": "echo",
            "input": {"text": "ping"},
        }
        output = next(chunk for chunk in result.chunks if chunk["type"] == "tool-output-available")
        assert output == {"type": "tool-output-available", "toolCallId": call_id, "output": {"text": "ping"}}
        deltas = "".join(str(chunk["inputTextDelta"]) for chunk in result.chunks if chunk["type"] == "tool-input-delta")
        assert deltas == '{"text": "ping"}'

        parts = result.finished.parts
        assert parts == fold_parts(result.ui_chunks)
        assert [part["type"] for part in parts] == [
            "step-start",
            "reasoning",
            "text",
            "tool-echo",
            "step-start",
            "text",
        ]
        assert parts[2]["text"] == "Let me check."
        assert parts[-1]["text"] == "Pong [1]."
        assert _tool_part(parts, call_id)["state"] == "output-available"

    async def test_step_completed_carries_messages_parts_and_usage(self, ctx: RunContext) -> None:
        turn_1 = scripted_turn("checking", tool_calls=[("echo", {"text": "a"})], input_tokens=100, output_tokens=20)
        _, built = scripted_model([turn_1, scripted_turn("done", input_tokens=150, output_tokens=30)])
        result = await collect(chat_graph(built, echo_tools(ctx)), ctx, prompt())

        kinds = [step.kind for step in result.steps]
        assert kinds == ["assistant", "tool", "assistant"]
        assert [step.step for step in result.steps] == [1, 2, 3]
        assistant, tool, final = result.steps
        assert isinstance(assistant.messages[0], AIMessage)
        assert assistant.messages[0].tool_calls[0]["name"] == "echo"
        assert isinstance(tool.messages[0], ToolMessage)
        assert tool.messages[0].artifact == {"output": {"text": "a"}, "is_error": False}
        assert assistant.usage.total.input_tokens == 100
        assert final.usage.total.input_tokens == 250
        assert final.usage.total.output_tokens == 50
        assert final.usage.by_model["scripted"].total_tokens == 300
        assert result.finished.usage == final.usage
        assert [part["type"] for part in assistant.parts] == ["step-start", "text", "tool-echo"]
        assert final.parts == result.finished.parts

    async def test_parallel_tool_calls_land_in_one_step(self, ctx: RunContext) -> None:
        turn = scripted_turn(tool_calls=[("echo", {"text": "one"}), ("echo", {"text": "two"})])
        _, built = scripted_model([turn, scripted_turn("both")])
        result = await collect(chat_graph(built, echo_tools(ctx)), ctx, prompt())
        tool_steps = [step for step in result.steps if step.kind == "tool"]
        assert len(tool_steps) == 1
        assert len(tool_steps[0].messages) == 2
        outputs = [chunk for chunk in result.chunks if chunk["type"] == "tool-output-available"]
        assert {str(chunk["output"]) for chunk in outputs} == {"{'text': 'one'}", "{'text': 'two'}"}
        assert ctx.budget.calls_made == 2

    async def test_invalid_arguments_become_a_tool_error(self, ctx: RunContext) -> None:
        turn = scripted_turn(tool_calls=[("echo", {"wrong": 1})])
        model, built = scripted_model([turn, scripted_turn("sorry")])
        result = await collect(chat_graph(built, echo_tools(ctx)), ctx, prompt())
        error = next(chunk for chunk in result.chunks if chunk["type"] == "tool-output-error")
        assert error["toolCallId"] == turn.tool_calls[0]["id"]
        assert "Invalid arguments for echo" in str(error["errorText"])
        # The model saw the error and answered; the run finished normally.
        assert isinstance(model.calls[1][-1], ToolMessage)
        assert model.calls[1][-1].status == "error"
        assert result.finished.stop.reason == "end"

    async def test_tool_failures_never_fail_the_run(self, ctx: RunContext) -> None:
        turn = scripted_turn(
            tool_calls=[("echo", {"text": "x", "fail": "app"}), ("echo", {"text": "y", "fail": "bug"})]
        )
        _, built = scripted_model([turn, scripted_turn("recovered")])
        result = await collect(chat_graph(built, echo_tools(ctx)), ctx, prompt())
        errors = {
            str(chunk["toolCallId"]): str(chunk["errorText"])
            for chunk in result.chunks
            if chunk["type"] == "tool-output-error"
        }
        assert errors[str(turn.tool_calls[0]["id"])] == "Tool failed: echo service down"
        assert errors[str(turn.tool_calls[1]["id"])] == "The tool failed unexpectedly. Continue without it."
        assert result.finished.stop.reason == "end"
        assert result.finished.error is None

    async def test_unknown_tool_name_is_reported_to_the_model(self, ctx: RunContext) -> None:
        turn = scripted_turn(tool_calls=[("nope", {})])
        _, built = scripted_model([turn, scripted_turn("ok")])
        result = await collect(chat_graph(built, echo_tools(ctx)), ctx, prompt())
        error = next(chunk for chunk in result.chunks if chunk["type"] == "tool-output-error")
        assert "not a valid tool" in str(error["errorText"])


class TestLimits:
    async def test_tool_budget_routes_to_budget_exceeded_and_forces_a_final_answer(self, ctx: RunContext) -> None:
        turns = [scripted_turn(tool_calls=[("echo", {"text": str(i)})]) for i in range(3)] + [scripted_turn("final")]
        model, built = scripted_model(turns)
        limits = AgentLimits(max_model_calls=12, max_tool_calls=2, max_tool_calls_per_step=8)
        result = await collect(chat_graph(built, echo_tools(ctx), limits), ctx, prompt(), limits=limits)
        errors = [chunk for chunk in result.chunks if chunk["type"] == "tool-output-error"]
        assert len(errors) == 1
        assert errors[0]["errorText"] == "Tool budget exhausted — answer with what you have."
        # The final call was made without tools.
        assert len(model.bound_tools) == 3
        assert result.finished.stop.reason == "end"
        assert result.finished.parts[-1]["text"] == "final"

    async def test_per_step_tool_limit(self, ctx: RunContext) -> None:
        turn = scripted_turn(tool_calls=[("echo", {"text": "a"}), ("echo", {"text": "b"}), ("echo", {"text": "c"})])
        _, built = scripted_model([turn, scripted_turn("ok")])
        limits = AgentLimits(max_tool_calls_per_step=2)
        result = await collect(chat_graph(built, echo_tools(ctx), limits), ctx, prompt(), limits=limits)
        assert len([chunk for chunk in result.chunks if chunk["type"] == "tool-output-error"]) == 3
        assert ctx.budget.calls_made == 0

    async def test_step_limit_ends_the_run(self, ctx: RunContext) -> None:
        turns = [scripted_turn(tool_calls=[("echo", {"text": str(i)})]) for i in range(5)]
        model, built = scripted_model(turns)
        limits = AgentLimits(max_model_calls=3)
        result = await collect(chat_graph(built, echo_tools(ctx), limits), ctx, prompt(), limits=limits)
        # Call 3 is the last permitted one and runs without tools; the script still calls a tool,
        # whose result is never executed; then the loop stops.
        assert len(model.calls) == 3
        assert model.bound_tools == [["echo"], ["echo"]]
        assert result.finished.stop.reason == "step_limit"
        assert result.chunks[-1] == {"type": "finish", "finishReason": "other"}


class TestStops:
    async def test_refusal_maps_to_content_filter(self, ctx: RunContext) -> None:
        _, built = scripted_model([scripted_turn("I can't help with that.", stop_reason="refusal")])
        result = await collect(chat_graph(built, echo_tools(ctx)), ctx, prompt())
        assert result.finished.stop.reason == "refusal"
        assert result.chunks[-1] == {"type": "finish", "finishReason": "content-filter"}

    async def test_max_tokens_with_tool_calls_executes_nothing(self, ctx: RunContext) -> None:
        turn = scripted_turn("partial", tool_calls=[("echo", {"text": "x"})], stop_reason="max_tokens")
        model, built = scripted_model([turn])
        result = await collect(chat_graph(built, echo_tools(ctx)), ctx, prompt())
        assert len(model.calls) == 1
        assert "tool-output-available" not in result.types
        assert result.finished.stop.reason == "length"
        assert result.chunks[-1] == {"type": "finish", "finishReason": "length"}
        tool_part = next(part for part in result.finished.parts if part["type"] == "tool-echo")
        assert tool_part["state"] == "input-available"

    async def test_model_failure_ends_with_an_error_chunk(self, ctx: RunContext) -> None:
        model, built = scripted_model([])
        model.failures[0] = TimeoutError()
        result = await collect(chat_graph(built, echo_tools(ctx)), ctx, prompt())
        assert result.chunks[-1] == {"type": "error", "errorText": "The assistant took too long to answer"}
        assert result.finished.stop.reason == "error"
        assert result.finished.error is not None
        assert result.finished.error.status_code == 503

    async def test_cancellation_aborts_the_run(self, ctx: RunContext) -> None:
        turn = scripted_turn(tool_calls=[("echo", {"text": "slow", "fail": "hang"})])
        _, built = scripted_model([turn, scripted_turn("never")])
        graph = chat_graph(built, echo_tools(ctx))

        async def cancel_soon() -> None:
            await asyncio.sleep(0.01)
            ctx.cancel.request("user")

        canceller = asyncio.ensure_future(cancel_soon())
        result = await collect(graph, ctx, prompt())
        await canceller
        assert result.chunks[-1] == {"type": "abort", "reason": "cancelled"}
        assert result.finished.stop.reason == "cancelled"
        assert "finish" not in result.types


class TestNoStream:
    async def test_nodes_outside_streamed_nodes_produce_no_parts(self, ctx: RunContext) -> None:
        _, built = scripted_model([scripted_turn("whole answer", reasoning="quietly")])
        # A node outside streamed_nodes contributes no parts at all; the run still ends properly.
        result = await collect(chat_graph(built, []), ctx, prompt(), streamed_nodes=frozenset({"other"}))
        assert result.types == ["finish"]
        assert result.finished.parts == []

    async def test_nostream_tag_is_replayed_as_whole_parts(self, ctx: RunContext) -> None:
        model, built = scripted_model([scripted_turn("whole answer", reasoning="quietly")])
        model.tags = ["nostream"]
        result = await collect(chat_graph(built, []), ctx, prompt())
        assert result.types == [
            "start-step",
            "reasoning-start",
            "reasoning-delta",
            "reasoning-end",
            "text-start",
            "text-delta",
            "text-end",
            "finish-step",
            "finish",
        ]
        assert result.finished.parts[1] == {"type": "reasoning", "text": "quietly", "state": "done"}
        assert result.finished.parts[2] == {"type": "text", "text": "whole answer", "state": "done"}
