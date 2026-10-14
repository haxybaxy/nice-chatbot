"""Turn the planner's JSON into a :class:`ResearchPlan` and scale it to the configured budget."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.core.research.prompts import parse_json_object
from app.core.research.types import Complexity, ResearchBudget, ResearchPlan, ResearchTask

_COMPLEXITIES: frozenset[str] = frozenset({"simple", "comparison", "complex"})
_CONTEXT_MAX_CHARS = 4000
_CITATION = re.compile(r"\[(\d{1,3})\]")
_DEFAULT_TASK_CALLS = 8


def scale_plan(plan: ResearchPlan, budget: ResearchBudget) -> ResearchPlan:
    """Server-side effort rule: the declared complexity bounds the task count and per-task calls."""
    if plan.complexity == "simple":
        max_tasks, max_calls = 1, min(10, budget.max_tool_calls_per_subagent)
    elif plan.complexity == "comparison":
        max_tasks, max_calls = min(4, budget.max_subagents), min(15, budget.max_tool_calls_per_subagent)
    else:
        max_tasks, max_calls = budget.max_subagents, budget.max_tool_calls_per_subagent
    tasks = tuple(
        ResearchTask(
            id=task.id,
            title=task.title,
            objective=task.objective,
            max_tool_calls=max(1, min(task.max_tool_calls, max_calls)),
        )
        for task in plan.tasks[:max_tasks]
    )
    return ResearchPlan(summary=plan.summary, complexity=plan.complexity, tasks=tasks)


def _task_from(entry: Mapping[str, object], index: int, seen: set[str]) -> ResearchTask | None:
    objective = entry.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        return None
    task_id = str(entry.get("id") or f"task-{index + 1}").strip() or f"task-{index + 1}"
    if task_id in seen:
        task_id = f"{task_id}-{index + 1}"
    seen.add(task_id)
    calls = entry.get("max_tool_calls")
    return ResearchTask(
        id=task_id,
        title=str(entry.get("title") or task_id).strip(),
        objective=objective.strip(),
        max_tool_calls=calls if isinstance(calls, int) and not isinstance(calls, bool) else _DEFAULT_TASK_CALLS,
    )


def parse_plan(text: str) -> ResearchPlan | None:
    """A :class:`ResearchPlan` from the planner's JSON, or ``None`` when it does not fit the schema."""
    raw = parse_json_object(text)
    if raw is None:
        return None
    complexity = raw.get("complexity")
    tasks_raw = raw.get("tasks")
    if complexity not in _COMPLEXITIES or not isinstance(tasks_raw, list):
        return None
    tasks: list[ResearchTask] = []
    seen: set[str] = set()
    for index, item in enumerate(cast("list[object]", tasks_raw)):
        task = _task_from(cast("Mapping[str, object]", item), index, seen) if isinstance(item, Mapping) else None
        if task is None:
            return None
        tasks.append(task)
    if not tasks:
        return None
    return ResearchPlan(
        summary=str(raw.get("summary") or "").strip(), complexity=cast("Complexity", complexity), tasks=tuple(tasks)
    )


def conversation_context(messages: Sequence[BaseMessage]) -> str:
    """Earlier user/assistant turns as plain text for the planner (the last human message is the question)."""
    lines: list[str] = []
    for message in messages[:-1]:
        if isinstance(message, HumanMessage):
            lines.append(f"User: {message.text}")
        elif isinstance(message, AIMessage) and message.text:
            lines.append(f"Assistant: {message.text}")
    text = "\n".join(lines)
    return text[-_CONTEXT_MAX_CHARS:] if len(text) > _CONTEXT_MAX_CHARS else text


def cited_numbers(report: str) -> set[int]:
    return {int(match) for match in _CITATION.findall(report)}
