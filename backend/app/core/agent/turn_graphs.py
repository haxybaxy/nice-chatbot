"""Assemble one assistant turn's graph and mapped stream, per run mode.

The worker's ``RunAssistantTurn`` decides *what* runs (which run, which history, resume or fresh)
and persists what comes out; these builders decide *how*: which models with which purposes and
efforts, the chat loop or the research graph, the ``RunnableConfig`` and the wall-clock budget.
Both hand back the same :class:`TurnStream` — the events ``map_graph_stream`` yields — so the
worker's loop is identical for either mode.

Resume: a second attempt continues its LangGraph thread (``astream(None)``) only when that thread
holds a checkpoint; a run that never got that far, or one under ``NullCheckpointer``, starts over
with the full input.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Collection, Sequence
from dataclasses import dataclass
from datetime import date

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.core.agent.events import MappedEvent
from app.core.agent.graph import AgentGraph, agent_input, build_agent_graph, run_config, stream_agent
from app.core.agent.state import AgentLimits
from app.core.agent.stream import map_graph_stream
from app.core.config import Effort, chat_settings
from app.core.llm.catalog import ModelCatalog, ModelSpec
from app.core.llm.chat_models import BuiltModel, ChatModelFactory
from app.core.llm.history import StoredMessage, to_langchain
from app.core.prompts import chat_system_message
from app.core.research.graph import (
    RESEARCH_STREAMED_NODES,
    ResearchGraph,
    build_research_graph,
    research_input,
    stream_research,
)
from app.core.research.prompts import CITATION_SCHEMA, PLAN_SCHEMA
from app.core.research.types import ResearchBudget
from app.core.tools.base import RunContext
from app.core.tools.registry import RunTools, ToolRegistry

CHAT_RUN_NAME = "chat"
RESEARCH_RUN_NAME = "deep_research"


@dataclass(frozen=True, slots=True)
class TurnSetup:
    """What both modes need from the worker."""

    llm: ChatModelFactory
    tools: ToolRegistry
    catalog: ModelCatalog
    spec: ModelSpec
    effort: Effort
    ctx: RunContext
    limits: AgentLimits
    saver: BaseCheckpointSaver[str] | None
    callbacks: Sequence[BaseCallbackHandler]
    # A later attempt: continue the thread when it holds a checkpoint.
    resume: bool


@dataclass(frozen=True, slots=True)
class TurnPrompt:
    """The per-conversation half of the system prompt."""

    product_name: str
    workspace_name: str
    user_display_name: str | None
    today: date
    # The tool names the run's options switch on; what is actually bound is resolved per mode.
    requested_tools: Collection[str]
    history: Sequence[StoredMessage]


# Deep research always searches: its subagents get the web tools whatever the switches say.
RESEARCH_TOOLS: frozenset[str] = frozenset({"web_search", "web_fetch"})


@dataclass(frozen=True, slots=True)
class TurnStream:
    events: AsyncGenerator[MappedEvent]
    timeout_s: float
    # Whether the graph continues an earlier attempt's thread (nothing is replayed to the model).
    resumed: bool


async def _resumes(setup: TurnSetup, graph: AgentGraph | ResearchGraph, config: RunnableConfig) -> bool:
    """``True`` when this attempt should ``astream(None)``: asked to resume and the thread has a checkpoint."""
    if not setup.resume or setup.saver is None:
        return False
    snapshot = await graph.aget_state(config)
    return snapshot.created_at is not None


def _system_prompt(model: BuiltModel, prompt: TurnPrompt, tools: RunTools) -> SystemMessage:
    """The prompt describes the tools that are bound, never the ones merely asked for."""
    return chat_system_message(
        model,
        product_name=prompt.product_name,
        workspace_name=prompt.workspace_name,
        user_display_name=prompt.user_display_name,
        today=prompt.today,
        enabled_tools=tools.names,
        unavailable_tools=tools.unavailable,
        native_web_search=tools.native_web_search,
    )


def _config(setup: TurnSetup, run_name: str) -> RunnableConfig:
    return run_config(
        thread_id=str(setup.ctx.run_id), limits=setup.limits, callbacks=setup.callbacks, run_name=run_name
    )


def _research_models(
    setup: TurnSetup, budget: ResearchBudget
) -> tuple[BuiltModel, BuiltModel, BuiltModel, BuiltModel | None]:
    """Planner and lead on the run's model, subagents on its cheaper sibling, the checker on the title model."""
    lead = setup.llm.build(setup.spec, effort=setup.effort, purpose="research_synthesis", user_id=setup.ctx.user_id)
    planner = setup.llm.build(
        setup.spec, effort="high", purpose="research_plan", output_schema=PLAN_SCHEMA, silent=True
    )
    worker = setup.llm.build(
        setup.catalog.cheaper(setup.spec),
        effort="low",
        purpose="research_task",
        max_tokens=budget.max_output_tokens_per_subagent,
        silent=True,
    )
    checker = None
    if budget.citation_check:
        checker = setup.llm.build(
            setup.catalog.title_model(),
            effort="low",
            purpose="research_citations",
            output_schema=CITATION_SCHEMA,
            silent=True,
        )
    return planner, lead, worker, checker


async def chat_turn(setup: TurnSetup, prompt: TurnPrompt) -> TurnStream:
    """The chat loop: the run's model with the enabled tools, resumed or fed the system prompt + history."""
    built = setup.llm.build(setup.spec, effort=setup.effort, purpose="chat", user_id=setup.ctx.user_id)
    tools = setup.tools.for_run(setup.ctx, names=prompt.requested_tools, spec=setup.spec)
    graph = build_agent_graph(built, tools, setup.limits, checkpointer=setup.saver, name=CHAT_RUN_NAME)
    config = _config(setup, CHAT_RUN_NAME)
    resumed = await _resumes(setup, graph, config)
    graph_input = None
    if not resumed:
        graph_input = agent_input([_system_prompt(built, prompt, tools), *to_langchain(prompt.history, setup.spec)])
    events = map_graph_stream(stream_agent(graph, graph_input, config, ctx=setup.ctx), ctx=setup.ctx)
    return TurnStream(events=events, timeout_s=chat_settings.chat_run_timeout_s, resumed=resumed)


async def research_turn(setup: TurnSetup, prompt: TurnPrompt, *, question: str) -> TurnStream:
    """Deep research under the smaller of the chat and research wall clocks."""
    budget = ResearchBudget.from_settings()
    planner, lead, worker, checker = _research_models(setup, budget)
    graph = build_research_graph(
        planner=planner,
        lead=lead,
        worker=worker,
        checker=checker,
        tools=setup.tools,
        budget=budget,
        checkpointer=setup.saver,
        name=RESEARCH_RUN_NAME,
    )
    config = _config(setup, RESEARCH_RUN_NAME)
    resumed = await _resumes(setup, graph, config)
    graph_input = None
    if not resumed:
        # The subagents do the searching, on the cheaper sibling: describe what they can do.
        tools = setup.tools.for_run(setup.ctx, names=RESEARCH_TOOLS | set(prompt.requested_tools), spec=worker.spec)
        messages = [_system_prompt(lead, prompt, tools), *to_langchain(prompt.history, setup.spec)]
        graph_input = research_input(messages, question)
    events = map_graph_stream(
        stream_research(graph, graph_input, config, ctx=setup.ctx),
        ctx=setup.ctx,
        streamed_nodes=RESEARCH_STREAMED_NODES,
    )
    timeout_s = min(chat_settings.chat_run_timeout_s, budget.wall_clock_s)
    return TurnStream(events=events, timeout_s=timeout_s, resumed=resumed)
