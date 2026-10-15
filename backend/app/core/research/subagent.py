"""One research task: the chat loop again, with a cheaper model, web tools only and a small budget.

The subagent shares the run's :class:`RunContext` — so its sources join the run-global ``[n]``
numbering, the cancel token reaches it and the token budget is debited — but runs its own
compiled agent graph without a checkpointer (a resumed research run re-runs the task; completed
findings are already in the parent checkpoint). Progress goes out as ``data-research-task``
chunks keyed by the task id, so the UI updates one card in place; the tools' own
``source-url`` / ``data-tool-progress`` chunks are forwarded unchanged.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from typing import cast

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.core.agent.citations import cite_content
from app.core.agent.graph import agent_input, build_agent_graph, run_config, stream_agent
from app.core.agent.server_tools import ServerSearch, server_searches
from app.core.agent.state import AgentLimits
from app.core.agent.usage import UsageTotals, usage_of
from app.core.exceptions import AppError
from app.core.llm.chat_models import BuiltModel
from app.core.logging_config import get_logger
from app.core.research.prompts import subagent_messages
from app.core.research.types import ResearchTask, TaskFinding, TaskStatus
from app.core.tools.base import ChunkWriter, RunContext
from app.core.tools.registry import ToolRegistry
from app.core.ui_stream import UI_CHUNK_ADAPTER, DataChunk, JsonObject, data_chunk

logger = get_logger(__name__)

SUBAGENT_TOOLS = frozenset({"web_search", "web_fetch"})
_SUMMARY_PREVIEW = 400


def task_chunk(
    task: ResearchTask,
    status: TaskStatus,
    *,
    tool_calls: int = 0,
    last_action: str | None = None,
    summary: str | None = None,
) -> DataChunk:
    data: JsonObject = {"id": task.id, "title": task.title, "status": status, "toolCalls": tool_calls}
    if last_action:
        data["lastAction"] = last_action
    if summary:
        data["summary"] = summary[:_SUMMARY_PREVIEW]
    return data_chunk("research-task", data, id=task.id)


def _describe_call(message: AIMessage) -> str | None:
    if not message.tool_calls:
        return None
    call = message.tool_calls[0]
    args = call["args"]
    detail = args.get("query") or args.get("url") or ""
    return f"{call['name']}: {detail}" if detail else call["name"]


def _describe_search(search: ServerSearch) -> str:
    detail = search.query or search.url or ""
    return f"{search.tool_name}: {detail}" if detail else search.tool_name


class _Progress:
    """What the task card shows, read off the inner graph's updates. Provider-executed searches count
    as tool calls too, and the final report gets its citations numbered through the run's sources."""

    def __init__(self, ctx: RunContext, write: ChunkWriter) -> None:
        self._ctx = ctx
        self._write = write
        self.tool_calls = 0
        self.usage = UsageTotals()
        self.last_action: str | None = None
        self.final_text = ""

    def absorb(self, update: Mapping[str, object]) -> None:
        messages = update.get("messages")
        if not isinstance(messages, list):
            return
        for message in cast("list[object]", messages):
            if not isinstance(message, AIMessage):
                continue
            self.usage = self.usage + usage_of(message)
            searches = server_searches(message.content)
            if searches:
                self.tool_calls += len(searches)
                self.last_action = _describe_search(searches[-1])
            if message.tool_calls:
                self.tool_calls += len(message.tool_calls)
                self.last_action = _describe_call(message)
            elif message.text:
                self.final_text = cite_content(message.content, self._ctx.sources, self._write)


async def run_research_task(
    *,
    task: ResearchTask,
    question: str,
    ctx: RunContext,
    worker: BuiltModel,
    tools: ToolRegistry,
    max_tool_calls_per_step: int,
    write: ChunkWriter,
) -> TaskFinding:
    """Run one task to a compressed finding; failures and budget exhaustion become statuses, not exceptions."""
    semaphore = ctx.research_semaphore if ctx.research_semaphore is not None else contextlib.nullcontext()
    progress = _Progress(ctx, write)
    limits = AgentLimits(
        max_model_calls=task.max_tool_calls + 2,
        max_tool_calls=task.max_tool_calls,
        max_tool_calls_per_step=max_tool_calls_per_step,
    )
    config = run_config(thread_id=f"{ctx.run_id}:{task.id}", limits=limits, run_name=f"research_task:{task.id}")
    try:
        async with semaphore:
            # Budget is checked once this task's turn comes: earlier tasks may have spent it.
            if ctx.token_budget is not None and ctx.token_budget.exhausted:
                write(task_chunk(task, "skipped", summary="Token budget exhausted before this task started."))
                return TaskFinding(
                    task_id=task.id,
                    status="skipped",
                    summary="Skipped: token budget exhausted.",
                    tool_calls=0,
                    usage=UsageTotals(),
                )
            write(task_chunk(task, "running"))
            graph = build_agent_graph(
                worker,
                tools.for_run(ctx, names=SUBAGENT_TOOLS, spec=worker.spec),
                limits,
                checkpointer=None,
                name=f"research_task:{task.id}",
            )
            events = stream_agent(graph, agent_input(subagent_messages(task, question)), config, ctx=ctx)
            async for event in events:
                _forward(event, progress, task, write)
    except (AppError, TimeoutError) as error:
        message = error.message if isinstance(error, AppError) else "The task timed out."
        logger.warning("research task failed", task_id=task.id, error=message)
        write(task_chunk(task, "failed", tool_calls=progress.tool_calls, summary=message))
        return TaskFinding(
            task_id=task.id,
            status="failed",
            summary=f"Failed: {message}",
            tool_calls=progress.tool_calls,
            usage=progress.usage,
        )
    if ctx.token_budget is not None:
        ctx.token_budget.spend(progress.usage.total_tokens)
    if ctx.cancel.requested or not progress.final_text:
        summary = "Cancelled before reporting." if ctx.cancel.requested else "The subagent produced no report."
        write(task_chunk(task, "failed", tool_calls=progress.tool_calls, summary=summary))
        return TaskFinding(
            task_id=task.id,
            status="failed",
            summary=f"Failed: {summary}",
            tool_calls=progress.tool_calls,
            usage=progress.usage,
        )
    write(task_chunk(task, "done", tool_calls=progress.tool_calls, summary=progress.final_text))
    return TaskFinding(
        task_id=task.id,
        status="done",
        summary=progress.final_text,
        tool_calls=progress.tool_calls,
        usage=progress.usage,
    )


def _forward(event: object, progress: _Progress, task: ResearchTask, write: ChunkWriter) -> None:
    """Route one inner-graph event: custom chunks pass through, node updates drive the task card."""
    if not isinstance(event, Mapping):
        return
    item = cast("Mapping[str, object]", event)
    kind = item.get("type")
    data = item.get("data")
    if kind == "custom":
        try:
            write(UI_CHUNK_ADAPTER.validate_python(data))
        except ValidationError:
            logger.warning("research task emitted an invalid chunk", task_id=task.id)
        return
    if kind != "updates" or not isinstance(data, Mapping):
        return
    for update in cast("Mapping[str, object]", data).values():
        if isinstance(update, Mapping):
            progress.absorb(cast("Mapping[str, object]", update))
    write(task_chunk(task, "running", tool_calls=progress.tool_calls, last_action=progress.last_action))
