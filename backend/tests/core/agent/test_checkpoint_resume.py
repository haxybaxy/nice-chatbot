"""Crash-resume: a run interrupted mid-tool-round continues from its checkpoint with ``astream(None)``."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from app.core.agent.graph import build_agent_graph, run_config
from app.core.agent.state import AgentLimits
from app.core.schemas import BaseSchema
from app.core.tools.base import RunContext, Tool, ToolCallContext, ToolResult, ToolSpec
from app.core.tools.registry import ToolRegistry
from tests.fakes_llm import OPUS, make_run_context, scripted_turn
from tests.graph_harness import collect, prompt, scripted_model


class LookupIn(BaseSchema):
    key: str = Field(max_length=50)


@dataclass
class _Flaky:
    """Hangs on its first invocation (the worker dies), answers on the next (the resumed worker)."""

    attempts: int = 0
    seen: list[str] = field(default_factory=list)

    async def run(self, call: ToolCallContext, args: LookupIn) -> ToolResult:
        del call
        self.attempts += 1
        self.seen.append(args.key)
        if self.attempts == 1:
            await asyncio.sleep(30)
        return ToolResult(content=f"value of {args.key}", output={"key": args.key})


def _tools(ctx: RunContext, flaky: _Flaky) -> list[BaseTool]:
    spec: ToolSpec = Tool(
        name="lookup", description="Looks up a key.", args_schema=LookupIn, requires=None, run=flaky.run
    )
    return ToolRegistry([spec]).for_run(ctx, names={"lookup"}, spec=OPUS)


async def test_interrupted_tool_round_resumes_from_the_checkpoint() -> None:
    saver = InMemorySaver()
    flaky = _Flaky()
    limits = AgentLimits()
    first_turn = scripted_turn("Looking it up.", tool_calls=[("lookup", {"key": "answer"})])

    # Attempt 1: the worker dies (task cancelled) while the tool is running.
    ctx_1 = make_run_context()
    _, built_1 = scripted_model([first_turn, scripted_turn("never reached")])
    graph_1 = build_agent_graph(built_1, _tools(ctx_1, flaky), limits, checkpointer=saver, name="chat")
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(collect(graph_1, ctx_1, prompt("what is the answer?")), 0.3)
    assert flaky.attempts == 1

    # Attempt 2: a new worker rebuilds the graph for the same thread and resumes with no input.
    ctx_2 = make_run_context(attempt=2)
    ctx_2.run_id = ctx_1.run_id
    model_2, built_2 = scripted_model([scripted_turn("The answer is 42.")])
    graph_2 = build_agent_graph(built_2, _tools(ctx_2, flaky), limits, checkpointer=saver, name="chat")
    result = await collect(graph_2, ctx_2, None)

    # Only the interrupted node re-ran: one more tool attempt, one more model call.
    assert flaky.attempts == 2
    assert flaky.seen == ["answer", "answer"]
    assert len(model_2.calls) == 1
    assert isinstance(model_2.calls[0][-1], ToolMessage)
    assert model_2.calls[0][-1].content == "value of answer"
    # The resumed stream starts with the tool output (the model step before it was already persisted).
    assert result.types[0] == "tool-output-available"
    assert result.first("tool-output-available")["toolCallId"] == first_turn.tool_calls[0]["id"]
    assert [step.kind for step in result.steps] == ["tool", "assistant"]
    assert result.finished.stop.reason == "end"
    assert result.finished.parts[-1]["text"] == "The answer is 42."

    state = await graph_2.aget_state(run_config(thread_id=str(ctx_1.run_id)))
    assert state.values["model_calls"] == 2
    await saver.adelete_thread(str(ctx_1.run_id))
    assert (await graph_2.aget_state(run_config(thread_id=str(ctx_1.run_id)))).values == {}
