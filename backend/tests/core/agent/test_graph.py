"""Graph semantics through ``ainvoke``: what the model sees, how the loop routes, what the state records."""

# Library boundary: CompiledStateGraph.ainvoke is typed with `Any`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.core.agent.graph import agent_input, run_config
from app.core.agent.state import AgentLimits, StopInfo, stop_info_for
from app.core.tools.base import RunContext
from tests.core.agent.conftest import chat_graph, echo_tools, prompt, scripted_model
from tests.fakes_llm import scripted_turn


class TestLoop:
    async def test_tool_round_trip_appends_messages_in_order(self, ctx: RunContext) -> None:
        turn = scripted_turn("checking", tool_calls=[("echo", {"text": "ping"})])
        model, built = scripted_model([turn, scripted_turn("pong")])
        state = await chat_graph(built, echo_tools(ctx)).ainvoke(
            agent_input(prompt("say ping")), run_config(thread_id="t"), context=ctx
        )
        messages = state["messages"]
        assert [type(message).__name__ for message in messages] == [
            "SystemMessage",
            "HumanMessage",
            "AIMessage",
            "ToolMessage",
            "AIMessage",
        ]
        tool_message = messages[3]
        assert isinstance(tool_message, ToolMessage)
        assert tool_message.content == "echo: ping"
        assert tool_message.tool_call_id == turn.tool_calls[0]["id"]
        # The second model call saw the full transcript including the tool result.
        assert [type(message).__name__ for message in model.calls[1]] == [
            "SystemMessage",
            "HumanMessage",
            "AIMessage",
            "ToolMessage",
        ]
        assert state["model_calls"] == 2
        assert state["tool_calls_made"] == 1
        assert state["stop"] == StopInfo("end")
        assert model.bound_tools == [["echo"], ["echo"]]

    async def test_without_tools_the_model_is_never_bound(self, ctx: RunContext) -> None:
        model, built = scripted_model([scripted_turn("plain")])
        state = await chat_graph(built, []).ainvoke(agent_input(prompt()), run_config(thread_id="t"), context=ctx)
        assert model.bound_tools == []
        assert isinstance(state["messages"][-1], AIMessage)
        assert state["messages"][-1].text == "plain"

    async def test_cancel_before_a_model_call_stops_without_calling(self, ctx: RunContext) -> None:
        model, built = scripted_model([scripted_turn("never")])
        ctx.cancel.request("user")
        state = await chat_graph(built, []).ainvoke(agent_input(prompt()), run_config(thread_id="t"), context=ctx)
        assert model.calls == []
        assert state["stop"] == StopInfo("cancelled")

    async def test_budget_exceeded_marks_final_answer_only(self, ctx: RunContext) -> None:
        turns = [
            scripted_turn(tool_calls=[("echo", {"text": "a"})]),
            scripted_turn(tool_calls=[("echo", {"text": "b"})]),
            scripted_turn("end"),
        ]
        model, built = scripted_model(turns)
        limits = AgentLimits(max_tool_calls=1)
        state = await chat_graph(built, echo_tools(ctx), limits).ainvoke(
            agent_input(prompt()),
            run_config(thread_id="t", limits=limits),
            context=ctx,
        )
        assert state["final_answer_only"] is True
        assert state["tool_calls_made"] == 2
        budget_message = state["messages"][-2]
        assert isinstance(budget_message, ToolMessage)
        assert budget_message.status == "error"
        # Third call: tools were not bound.
        assert model.bound_tools == [["echo"], ["echo"]]


class TestStopInfo:
    def test_anthropic_stop_reasons(self) -> None:
        assert stop_info_for(scripted_turn("x", stop_reason="end_turn")) == StopInfo("end")
        assert stop_info_for(scripted_turn("x", stop_reason="max_tokens")) == StopInfo("length")
        assert stop_info_for(scripted_turn("x", stop_reason="refusal")) == StopInfo("refusal")
        assert stop_info_for(scripted_turn(tool_calls=[("echo", {})])) is None

    def test_openai_finish_reasons_and_missing_metadata(self) -> None:
        assert stop_info_for(AIMessage(content="x", response_metadata={"finish_reason": "stop"})) == StopInfo("end")
        assert stop_info_for(AIMessage(content="x", response_metadata={"finish_reason": "content_filter"})) == StopInfo(
            "refusal"
        )
        assert stop_info_for(AIMessage(content="x", response_metadata={"finish_reason": "tool_calls"})) is None
        assert stop_info_for(AIMessage(content="x")) == StopInfo("end")
        bare_call = AIMessage(content="", tool_calls=[{"name": "echo", "args": {}, "id": "c", "type": "tool_call"}])
        assert stop_info_for(bare_call) is None

    def test_finish_reasons(self) -> None:
        assert StopInfo("end").finish_reason == "stop"
        assert StopInfo("refusal").finish_reason == "content-filter"
        assert StopInfo("step_limit").finish_reason == "other"
        assert AgentLimits(max_model_calls=12).recursion_limit == 28
        assert AgentLimits.from_settings() == AgentLimits(
            max_model_calls=12, max_tool_calls=24, max_tool_calls_per_step=8
        )


class TestInputShape:
    async def test_system_message_stays_first(self, ctx: RunContext) -> None:
        model, built = scripted_model([scripted_turn("ok")])
        await chat_graph(built, []).ainvoke(
            agent_input([SystemMessage(content="sys"), HumanMessage(content="q")]),
            run_config(thread_id="t"),
            context=ctx,
        )
        assert isinstance(model.calls[0][0], SystemMessage)
        assert model.calls[0][0].content == "sys"
