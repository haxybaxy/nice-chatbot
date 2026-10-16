"""Run the real chat graph offline: a scripted model, the per-run tools and the stream mapper.

Shared by the agent, tool and research tests. ``collect`` drives ``map_graph_stream`` exactly
the way the worker does and gathers chunks, step completions and the final ``RunFinished``;
``invoke_state`` runs the graph to its final state without the mapper.
"""

# Library boundary: CompiledStateGraph.ainvoke is typed with `Any`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from app.core.agent.graph import AgentGraph, agent_input, build_agent_graph, run_config, stream_agent
from app.core.agent.state import AgentLimits
from app.core.agent.stream import DEFAULT_STREAMED_NODES, RunFinished, StepCompleted, UIChunkEvent, map_graph_stream
from app.core.llm.chat_models import BuiltModel
from app.core.tools.base import RunContext
from app.core.tools.registry import RunTools, ToolRegistry, default_tool_registry
from app.core.ui_stream import UIChunk
from tests.fakes_llm import OPUS, FakeChatModelFactory, ScriptedChatModel


@dataclass
class Collected:
    ui_chunks: list[UIChunk]
    steps: list[StepCompleted]
    finished: RunFinished

    @property
    def chunks(self) -> list[dict[str, object]]:
        """The chunks as plain dicts (the wire shape), convenient to index in assertions."""
        return [dict(chunk) for chunk in self.ui_chunks]

    @property
    def types(self) -> list[str]:
        return [chunk["type"] for chunk in self.ui_chunks]

    def of_type(self, chunk_type: str) -> list[dict[str, object]]:
        return [chunk for chunk in self.chunks if chunk["type"] == chunk_type]

    def first(self, chunk_type: str) -> dict[str, object]:
        return self.of_type(chunk_type)[0]


def scripted_model(turns: Sequence[AIMessage], *, purpose: str = "chat") -> tuple[ScriptedChatModel, BuiltModel]:
    """A ``BuiltModel`` over a ``ScriptedChatModel`` playing ``turns``."""
    model = ScriptedChatModel(turns=list(turns))
    built = FakeChatModelFactory(by_purpose={purpose: model}).build(OPUS, effort="medium", purpose=purpose)
    return model, built


def tools_for(ctx: RunContext, names: Collection[str], registry: ToolRegistry | None = None) -> RunTools:
    return (registry or default_tool_registry()).for_run(ctx, names=names, spec=OPUS)


def run_tools(tools: Sequence[BaseTool]) -> RunTools:
    """Plain LangChain tools as a run's tool set (what `for_run` returns for client tools only)."""
    return RunTools(client=tuple(tools), names=tuple(sorted(tool.name for tool in tools)))


def chat_graph(
    built: BuiltModel, tools: RunTools | Sequence[BaseTool], limits: AgentLimits | None = None
) -> AgentGraph:
    resolved = tools if isinstance(tools, RunTools) else run_tools(tools)
    return build_agent_graph(built, resolved, limits or AgentLimits(), checkpointer=None, name="chat")


def prompt(text: str = "hi") -> list[BaseMessage]:
    return [SystemMessage(content="You are a test."), HumanMessage(content=text)]


async def collect(
    graph: AgentGraph,
    ctx: RunContext,
    messages: Sequence[BaseMessage] | None,
    *,
    limits: AgentLimits | None = None,
    streamed_nodes: frozenset[str] = DEFAULT_STREAMED_NODES,
) -> Collected:
    """Run ``graph`` through ``map_graph_stream`` and gather everything it yields (``None`` resumes)."""
    config = run_config(thread_id=str(ctx.run_id), limits=limits)
    events = stream_agent(graph, agent_input(messages) if messages is not None else None, config, ctx=ctx)
    chunks: list[UIChunk] = []
    steps: list[StepCompleted] = []
    finished: RunFinished | None = None
    async for event in map_graph_stream(events, ctx=ctx, streamed_nodes=streamed_nodes):
        if isinstance(event, UIChunkEvent):
            chunks.append(event.chunk)
        elif isinstance(event, StepCompleted):
            steps.append(event)
        else:
            finished = event
    assert finished is not None, "map_graph_stream must end with RunFinished"
    return Collected(ui_chunks=chunks, steps=steps, finished=finished)


async def invoke_state(
    graph: AgentGraph, ctx: RunContext, messages: Sequence[BaseMessage], *, limits: AgentLimits | None = None
) -> dict[str, object]:
    """Run ``graph`` to completion and return its final state (no stream mapping)."""
    config = run_config(thread_id=str(ctx.run_id), limits=limits)
    return cast("dict[str, object]", await graph.ainvoke(agent_input(messages), config, context=ctx))
