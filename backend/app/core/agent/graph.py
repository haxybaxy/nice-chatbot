"""The chat loop as an explicit LangGraph ``StateGraph``: model → tools → model, with budgets.

Nodes: ``agent`` calls the model (tools bound unless the budget node asked for a final answer or
this is the last permitted call), counts calls and derives the provider's stop reason; ``tools``
runs the step's tool calls in parallel (``ToolNode``); ``budget_exceeded`` answers every pending
call with an error result and forces a tool-less final answer. ``route_after_agent`` ends the loop
on a stop (end of turn, refusal, ``max_tokens`` — even with tool calls pending, which then run
nowhere) or when there are no tool calls.

Compiled with a checkpointer and invoked with ``configurable.thread_id = run_id``, an interrupted
run resumes from its last completed node with ``astream(None, config)``. The deep-research
subagents reuse this graph with a cheaper model and no checkpointer.

Why not ``create_agent`` + middleware: the limits and refusal routing would live in ``Any``-typed
hooks, the research graph needs a raw ``StateGraph`` anyway, and this is ~100 lines that are unit
tested chunk by chunk.
"""

# Library boundary: LangGraph node signatures and state updates are `dict[str, Any]`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import cast

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs] — no py.typed
from langgraph.graph.state import CompiledStateGraph  # pyright: ignore[reportMissingTypeStubs] — no py.typed
from langgraph.runtime import Runtime

from app.core.agent.state import AgentLimits, AgentState, StopInfo, stop_info_for
from app.core.llm.chat_models import BuiltModel
from app.core.tools.base import RunContext
from app.core.tools.registry import BUDGET_EXHAUSTED, RunTools, build_tool_node

AGENT_NODE = "agent"
TOOLS_NODE = "tools"
BUDGET_NODE = "budget_exceeded"
type AgentGraph = CompiledStateGraph[AgentState, RunContext, AgentState, AgentState]
# What `map_graph_stream` consumes: token chunks, per-node state updates and the tools' custom chunks.
STREAM_MODES = ("messages", "updates", "custom")


def agent_input(messages: Sequence[BaseMessage]) -> AgentState:
    """The graph input for a fresh run: system prompt, history and the new user message."""
    return AgentState(messages=cast(list[AnyMessage], list(messages)))


def run_config(
    *,
    thread_id: str,
    limits: AgentLimits | None = None,
    callbacks: Sequence[BaseCallbackHandler] = (),
    run_name: str = "chat",
) -> RunnableConfig:
    """The ``RunnableConfig`` for one run: checkpoint thread, recursion limit, tracer callbacks."""
    return RunnableConfig(
        configurable={"thread_id": thread_id},
        recursion_limit=(limits or AgentLimits()).recursion_limit,
        callbacks=list(callbacks),
        run_name=run_name,
    )


def stream_agent(
    graph: AgentGraph, input: AgentState | None, config: RunnableConfig, *, ctx: RunContext
) -> AsyncIterator[object]:
    """``graph.astream`` in the one shape ``map_graph_stream`` understands; ``input=None`` resumes ``thread_id``."""
    return graph.astream(input, config, context=ctx, stream_mode=list(STREAM_MODES), version="v2", subgraphs=True)


def build_agent_graph(
    model: BuiltModel,
    tools: RunTools,
    limits: AgentLimits,
    *,
    checkpointer: BaseCheckpointSaver[str] | None,
    name: str = "chat",
) -> AgentGraph:
    """Compile the loop for one run. ``tools`` are already resolved for the run (``ToolRegistry.for_run``):
    the model is bound to client and provider tools alike, the ``ToolNode`` runs only the client ones."""
    bound = tools.bound

    async def agent(state: AgentState, runtime: Runtime[RunContext]) -> dict[str, object]:
        calls = state.get("model_calls", 0)
        if calls >= limits.max_model_calls:
            return {"stop": StopInfo("step_limit", explanation=f"{limits.max_model_calls} model calls")}
        if runtime.context.cancel.requested:
            return {"stop": StopInfo("cancelled")}
        # The last permitted call never gets tools, so the loop always ends with an answer.
        last_call = calls >= limits.max_model_calls - 1
        use_tools = bool(tools) and not state.get("final_answer_only", False) and not last_call
        response = await model.runnable(bound if use_tools else ()).ainvoke(state["messages"])
        update: dict[str, object] = {"messages": [response], "model_calls": calls + 1}
        if response.tool_calls:
            update["tool_calls_made"] = state.get("tool_calls_made", 0) + len(response.tool_calls)
        stop = stop_info_for(response)
        if stop is not None:
            update["stop"] = stop
        return update

    def route_after_agent(state: AgentState) -> str:
        if state.get("stop") is not None:
            return END
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return END
        pending = len(last.tool_calls)
        made_before = state.get("tool_calls_made", 0) - pending
        if pending > limits.max_tool_calls_per_step or made_before + pending > limits.max_tool_calls:
            return BUDGET_NODE
        return TOOLS_NODE

    async def budget_exceeded(state: AgentState) -> dict[str, object]:
        last = state["messages"][-1]
        calls = last.tool_calls if isinstance(last, AIMessage) else []
        return {
            "messages": [
                ToolMessage(content=BUDGET_EXHAUSTED, tool_call_id=str(call["id"]), name=call["name"], status="error")
                for call in calls
            ],
            "final_answer_only": True,
        }

    graph = StateGraph(AgentState, context_schema=RunContext)
    graph.add_node(AGENT_NODE, agent)
    graph.add_node(TOOLS_NODE, build_tool_node(tools.client))
    graph.add_node(BUDGET_NODE, budget_exceeded)
    graph.add_edge(START, AGENT_NODE)
    graph.add_conditional_edges(AGENT_NODE, route_after_agent, [TOOLS_NODE, BUDGET_NODE, END])
    graph.add_edge(TOOLS_NODE, AGENT_NODE)
    graph.add_edge(BUDGET_NODE, AGENT_NODE)
    return graph.compile(checkpointer=checkpointer, name=name)
