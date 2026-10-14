"""Deep research as a LangGraph graph: plan → parallel subagents → synthesis → citation check.

``plan`` asks the planner (structured output) for tasks and scales them server-side by the
declared complexity; ``fan_out`` sends one ``research_task`` per task (``Send``), each running the
chat loop with the cheaper worker model and the web tools under a shared semaphore and token
budget; ``synthesize`` streams the report from the lead model (the only node the stream mapper
renders as text); ``citation_check`` asks the checker which ``[n]`` citations look unsupported
and reports them as a ``data-research-citations`` part (warnings only in v1).

Consumed by ``map_graph_stream(..., streamed_nodes={"synthesize"})``. The wall clock
(``ResearchBudget.wall_clock_s``) is enforced by the worker around the whole stream.
"""

# Library boundary: LangGraph node signatures, `Send` payloads and state updates are `dict[str, Any]`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import cast

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs] — no py.typed
from langgraph.graph.state import CompiledStateGraph  # pyright: ignore[reportMissingTypeStubs] — no py.typed
from langgraph.runtime import Runtime
from langgraph.types import Send

from app.core.agent.graph import STREAM_MODES
from app.core.agent.state import StopInfo, stop_info_for
from app.core.agent.usage import UsageTotals, usage_of
from app.core.exceptions import AppError
from app.core.llm.chat_models import BuiltModel
from app.core.logging_config import get_logger
from app.core.research.plan import cited_numbers, conversation_context, parse_plan, scale_plan
from app.core.research.prompts import (
    citation_messages,
    parse_json_object,
    planner_messages,
    retry_plan_message,
    synthesis_messages,
)
from app.core.research.subagent import run_research_task
from app.core.research.types import CitationCheck, ResearchBudget, ResearchState, TaskFinding, TaskInput
from app.core.tools.base import RunContext, TokenBudget
from app.core.tools.registry import ToolRegistry
from app.core.ui_stream import data_chunk

logger = get_logger(__name__)

PLAN_NODE = "plan"
TASK_NODE = "research_task"
SYNTHESIZE_NODE = "synthesize"
CITATIONS_NODE = "citation_check"
RESEARCH_STREAMED_NODES: frozenset[str] = frozenset({SYNTHESIZE_NODE})
type ResearchGraph = CompiledStateGraph[ResearchState, RunContext, ResearchState, ResearchState]


def research_input(messages: Sequence[BaseMessage], question: str) -> ResearchState:
    """Graph input: the conversation so far (system prompt, history, the question last) plus the question text."""
    return cast("ResearchState", {"messages": list(messages), "question": question})


def stream_research(
    graph: ResearchGraph, input: ResearchState | None, config: RunnableConfig, *, ctx: RunContext
) -> AsyncIterator[object]:
    """``graph.astream`` in the shape ``map_graph_stream`` understands; ``input=None`` resumes ``thread_id``."""
    return graph.astream(input, config, context=ctx, stream_mode=list(STREAM_MODES), version="v2", subgraphs=True)


# ── Graph ────────────────────────────────────────────────────────────────────


def build_research_graph(
    *,
    planner: BuiltModel,
    lead: BuiltModel,
    worker: BuiltModel,
    checker: BuiltModel | None,
    tools: ToolRegistry,
    budget: ResearchBudget,
    checkpointer: BaseCheckpointSaver[str] | None,
    name: str = "deep_research",
) -> ResearchGraph:
    """Compile the research graph for one run.

    ``planner`` is the lead model built with ``output_schema=PLAN_SCHEMA`` (silent); ``lead`` streams
    the synthesis; ``worker`` is the cheaper model the subagents run on; ``checker`` (``None`` to
    skip) is the title model built with ``output_schema=CITATION_SCHEMA``.
    """

    async def plan(state: ResearchState, runtime: Runtime[RunContext]) -> dict[str, object]:
        ctx = runtime.context
        if ctx.research_semaphore is None:
            ctx.research_semaphore = asyncio.Semaphore(max(1, budget.max_parallel))
        if ctx.token_budget is None:
            ctx.token_budget = TokenBudget(limit=budget.total_token_budget)
        messages = planner_messages(
            state.get("question", ""),
            context=conversation_context(state.get("messages", [])),
            max_tasks=budget.max_subagents,
            max_calls=budget.max_tool_calls_per_subagent,
        )
        runnable = planner.runnable()
        response = await runnable.ainvoke(messages)
        usage = usage_of(response)
        parsed = parse_plan(response.text)
        if parsed is None:
            logger.warning("research plan unparsable, retrying once")
            response = await runnable.ainvoke([*messages, response, retry_plan_message()])
            usage = usage + usage_of(response)
            parsed = parse_plan(response.text)
        if parsed is None:
            explanation = "Could not plan the research; please rephrase the question"
            return {"stop": StopInfo("error", explanation=explanation), "usage": [usage]}
        scaled = scale_plan(parsed, budget)
        runtime.stream_writer(data_chunk("research-plan", scaled.as_data(), id="plan"))
        return {"plan": scaled, "usage": [usage]}

    def fan_out(state: ResearchState) -> list[Send] | str:
        plan_value = state.get("plan")
        if state.get("stop") is not None or plan_value is None:
            return END
        question = state.get("question", "")
        return [Send(TASK_NODE, TaskInput(task=task, question=question)) for task in plan_value.tasks]

    async def research_task(state: TaskInput, runtime: Runtime[RunContext]) -> dict[str, object]:
        finding = await run_research_task(
            task=state["task"],
            question=state["question"],
            ctx=runtime.context,
            worker=worker,
            tools=tools,
            max_tool_calls_per_step=4,
            write=runtime.stream_writer,
        )
        return {"findings": [finding], "usage": [finding.usage]}

    async def synthesize(state: ResearchState, runtime: Runtime[RunContext]) -> dict[str, object]:
        findings: list[TaskFinding] = list(state.get("findings", []))
        if runtime.context.cancel.requested:
            return {"stop": StopInfo("cancelled")}
        if not any(finding.status == "done" for finding in findings):
            return {"stop": StopInfo("error", explanation="Research produced no findings to synthesize")}
        response = await lead.runnable().ainvoke(
            synthesis_messages(state.get("question", ""), findings, runtime.context.sources.all())
        )
        update: dict[str, object] = {"messages": [response], "report": response.text}
        stop = stop_info_for(response)
        if stop is not None and stop.reason != "end":
            update["stop"] = stop
        return update

    async def citation_check(state: ResearchState, runtime: Runtime[RunContext]) -> dict[str, object]:
        report = state.get("report", "")
        if not budget.citation_check or checker is None or not report or state.get("stop") is not None:
            return {}
        sources = runtime.context.sources.all()
        known = {source.id for source in sources}
        unknown = tuple(sorted(number for number in cited_numbers(report) if number not in known))
        unsupported: tuple[str, ...] = ()
        usage = UsageTotals()
        try:
            response = await checker.runnable().ainvoke(citation_messages(report, sources))
            usage = usage_of(response)
            verdict = parse_json_object(response.text) or {}
            raw = verdict.get("unsupported")
            if isinstance(raw, list):
                unsupported = tuple(str(item) for item in cast("list[object]", raw))
        except AppError as error:
            logger.warning("citation check skipped", error=error.message)
        check = CitationCheck(unsupported=unsupported, unknown_numbers=unknown)
        runtime.stream_writer(data_chunk("research-citations", check.as_data(), id="citations"))
        return {"citations": check, "usage": [usage]}

    graph = StateGraph(ResearchState, context_schema=RunContext)
    graph.add_node(PLAN_NODE, plan)
    graph.add_node(TASK_NODE, research_task, input_schema=TaskInput)
    graph.add_node(SYNTHESIZE_NODE, synthesize)
    graph.add_node(CITATIONS_NODE, citation_check)
    graph.add_edge(START, PLAN_NODE)
    graph.add_conditional_edges(PLAN_NODE, fan_out, [TASK_NODE, END])
    graph.add_edge(TASK_NODE, SYNTHESIZE_NODE)
    graph.add_edge(SYNTHESIZE_NODE, CITATIONS_NODE)
    graph.add_edge(CITATIONS_NODE, END)
    return graph.compile(checkpointer=checkpointer, name=name)
