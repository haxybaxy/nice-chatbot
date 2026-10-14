"""Deep-research vocabulary: the plan, its tasks, what a subagent brings back, budgets and graph state."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

from langgraph.graph import MessagesState  # pyright: ignore[reportMissingTypeStubs] — no py.typed

from app.core.agent.state import StopInfo
from app.core.agent.usage import UsageTotals
from app.core.config import research_settings
from app.core.ui_stream import JsonObject

type TaskStatus = Literal["pending", "running", "done", "failed", "skipped"]
type Complexity = Literal["simple", "comparison", "complex"]


@dataclass(frozen=True, slots=True)
class ResearchTask:
    id: str
    title: str
    objective: str
    max_tool_calls: int

    def as_data(self, status: TaskStatus = "pending") -> JsonObject:
        return {"id": self.id, "title": self.title, "objective": self.objective, "status": status}


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    summary: str
    complexity: Complexity
    tasks: tuple[ResearchTask, ...]

    def as_data(self) -> JsonObject:
        """Payload of the ``data-research-plan`` part (``id="plan"``)."""
        return {
            "summary": self.summary,
            "complexity": self.complexity,
            "tasks": [task.as_data() for task in self.tasks],
        }


@dataclass(frozen=True, slots=True)
class TaskFinding:
    task_id: str
    status: TaskStatus
    # Compressed findings with [n] citations (done), or why there are none (failed / skipped).
    summary: str
    tool_calls: int
    usage: UsageTotals


@dataclass(frozen=True, slots=True)
class CitationCheck:
    unsupported: tuple[str, ...]
    unknown_numbers: tuple[int, ...]

    def as_data(self) -> JsonObject:
        return {"unsupported": list(self.unsupported), "unknownNumbers": list(self.unknown_numbers)}


@dataclass(frozen=True, slots=True)
class ResearchBudget:
    max_subagents: int = 5
    max_parallel: int = 3
    max_tool_calls_per_subagent: int = 12
    max_output_tokens_per_subagent: int = 16_000
    total_token_budget: int = 400_000
    wall_clock_s: int = 600
    citation_check: bool = True

    @classmethod
    def from_settings(cls) -> ResearchBudget:
        return cls(
            max_subagents=research_settings.research_max_subagents,
            max_parallel=research_settings.research_max_parallel,
            max_tool_calls_per_subagent=research_settings.research_max_tool_calls_per_subagent,
            max_output_tokens_per_subagent=research_settings.research_max_output_tokens_per_subagent,
            total_token_budget=research_settings.research_total_token_budget,
            wall_clock_s=research_settings.research_wall_clock_s,
            citation_check=research_settings.research_citation_check,
        )


class ResearchState(MessagesState, total=False):
    """``messages`` holds the conversation (system prompt, history, question) and the synthesized report."""

    question: str
    plan: ResearchPlan | None
    findings: Annotated[list[TaskFinding], operator.add]
    # Subagent usage, one entry per task; the stream mapper folds it into the run's usage.
    usage: Annotated[list[UsageTotals], operator.add]
    report: str
    citations: CitationCheck | None
    stop: StopInfo | None


class TaskInput(TypedDict):
    """What ``Send`` hands to one ``research_task`` node."""

    task: ResearchTask
    question: str
