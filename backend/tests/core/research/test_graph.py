"""The research graph end to end, offline: plan → subagents → synthesis → citations, as the UI sees it."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.agent.graph import run_config
from app.core.agent.stream import RunFinished, StepCompleted, UIChunkEvent, map_graph_stream
from app.core.exceptions import AppError
from app.core.research.graph import (
    RESEARCH_STREAMED_NODES,
    ResearchGraph,
    build_research_graph,
    research_input,
    stream_research,
)
from app.core.research.plan import parse_plan, scale_plan
from app.core.research.prompts import parse_json_object
from app.core.research.types import ResearchBudget, ResearchPlan, ResearchTask
from app.core.search import SearchResult
from app.core.tools.base import RunContext
from app.core.tools.registry import default_tool_registry
from app.core.ui_stream import UIChunk
from tests.fakes_llm import (
    HAIKU,
    OPUS,
    SONNET,
    FakeChatModelFactory,
    FakeSearchClient,
    ScriptedChatModel,
    make_run_context,
    scripted_turn,
)

QUESTION = "Should we pick A or B?"
PLAN = {
    "summary": "Compare A and B on speed and cost.",
    "complexity": "comparison",
    "tasks": [
        {"id": "a", "title": "Option A", "objective": "Find how fast A is.", "max_tool_calls": 20},
        {"id": "b", "title": "Option B", "objective": "Find how cheap B is.", "max_tool_calls": 5},
    ],
}
A_URL = "https://a.example/"
B_URL = "https://b.example/"
RESULTS = {
    "A speed": [SearchResult(url=A_URL, title="A docs", snippet="A is fast", published_at=None, score=0.9)],
    "B price": [
        SearchResult(url=B_URL, title="B pricing", snippet="B is cheap", published_at=None, score=0.9),
        SearchResult(url=A_URL, title="A docs", snippet="A again", published_at=None, score=0.5),
    ],
}


@dataclass
class Models:
    planner: ScriptedChatModel = field(
        default_factory=lambda: ScriptedChatModel(turns=[scripted_turn(json.dumps(PLAN))])
    )
    worker: ScriptedChatModel = field(default_factory=ScriptedChatModel)
    lead: ScriptedChatModel = field(default_factory=ScriptedChatModel)
    checker: ScriptedChatModel = field(
        default_factory=lambda: ScriptedChatModel(turns=[scripted_turn('{"unsupported": ["B is cheap"]}')])
    )


def worker_turns() -> list[AIMessage]:
    return [
        scripted_turn(tool_calls=[("web_search", {"query": "A speed"})]),
        scripted_turn("Findings:\n- A is fast [1]\nSources:\n- [1] A docs\nConfidence: high\nGaps: none"),
        scripted_turn(tool_calls=[("web_search", {"query": "B price"})]),
        scripted_turn("Findings:\n- B is cheap [2]\nSources:\n- [2] B pricing\nConfidence: medium\nGaps: none"),
    ]


def lead_turns() -> list[AIMessage]:
    return [
        scripted_turn(
            "# A or B\n\nA is fast [1] while B is cheap [2]. Unverified [9].\n\n## Confidence & gaps\nMedium."
        )
    ]


@dataclass
class Research:
    chunks: list[UIChunk]
    steps: list[StepCompleted]
    finished: RunFinished

    @property
    def types(self) -> list[str]:
        return [chunk["type"] for chunk in self.chunks]

    def of_type(self, chunk_type: str) -> list[dict[str, object]]:
        return [dict(chunk) for chunk in self.chunks if chunk["type"] == chunk_type]


def _graph(models: Models, budget: ResearchBudget, *, with_checker: bool = True) -> ResearchGraph:
    factory = FakeChatModelFactory(
        by_purpose={
            "research_plan": models.planner,
            "research_task": models.worker,
            "research_synthesis": models.lead,
            "research_citations": models.checker,
        }
    )
    return build_research_graph(
        planner=factory.build(OPUS, effort="high", purpose="research_plan", silent=True),
        lead=factory.build(OPUS, effort="medium", purpose="research_synthesis"),
        worker=factory.build(SONNET, effort="low", purpose="research_task", silent=True),
        checker=factory.build(HAIKU, effort="low", purpose="research_citations", silent=True) if with_checker else None,
        tools=default_tool_registry(),
        budget=budget,
        checkpointer=None,
    )


async def _run(graph: ResearchGraph, ctx: RunContext, question: str = QUESTION) -> Research:
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="earlier"),
        AIMessage(content="noted"),
        HumanMessage(content=question),
    ]
    events = stream_research(
        graph,
        research_input(messages, question),
        run_config(thread_id=str(ctx.run_id), run_name="deep_research"),
        ctx=ctx,
    )
    chunks: list[UIChunk] = []
    steps: list[StepCompleted] = []
    finished: RunFinished | None = None
    async for event in map_graph_stream(events, ctx=ctx, streamed_nodes=RESEARCH_STREAMED_NODES):
        if isinstance(event, UIChunkEvent):
            chunks.append(event.chunk)
        elif isinstance(event, StepCompleted):
            steps.append(event)
        else:
            finished = event
    assert finished is not None
    return Research(chunks=chunks, steps=steps, finished=finished)


SERIAL = ResearchBudget(max_parallel=1)


def _data(card: Mapping[str, object]) -> dict[str, object]:
    data = card["data"]
    assert isinstance(data, dict)
    return cast("dict[str, object]", data)


class TestHappyPath:
    async def test_plan_tasks_synthesis_and_citations_in_order(self) -> None:
        models = Models(worker=ScriptedChatModel(turns=worker_turns()), lead=ScriptedChatModel(turns=lead_turns()))
        search = FakeSearchClient(results=RESULTS)
        ctx = make_run_context(search=search)
        result = await _run(_graph(models, SERIAL), ctx)

        # The plan comes first, with every task pending.
        plan = dict(result.chunks[0])
        assert plan["type"] == "data-research-plan"
        assert plan.get("id") == "plan"
        plan_data = _data(plan)
        assert plan_data["complexity"] == "comparison"
        plan_tasks = cast("list[dict[str, object]]", plan_data["tasks"])
        assert [task["status"] for task in plan_tasks] == ["pending", "pending"]
        # The planner saw the earlier conversation as context, not as the question.
        planner_prompt = str(models.planner.calls[0][-1].content)
        assert "Question:\nShould we pick A or B?" in planner_prompt
        assert "User: earlier" in planner_prompt

        # Tasks report running → done in place (same id), serially under max_parallel=1.
        cards = result.of_type("data-research-task")
        a_cards = [card for card in cards if card["id"] == "a"]
        b_cards = [card for card in cards if card["id"] == "b"]
        assert _data(a_cards[0])["status"] == "running"
        assert _data(a_cards[-1])["status"] == "done"
        assert _data(a_cards[-1])["toolCalls"] == 1
        assert str(_data(a_cards[-1])["summary"]).startswith("Findings:")
        assert cards.index(a_cards[-1]) < cards.index(b_cards[0])

        # Sources are numbered run-globally and streamed once; A's URL is not renumbered by task b.
        assert [(chunk["sourceId"], chunk["url"]) for chunk in result.of_type("source-url")] == [
            ("1", A_URL),
            ("2", B_URL),
        ]
        assert "data-tool-progress" in result.types  # the inner tools' chunks are forwarded
        assert "[1] A docs" in str(models.worker.calls[3][-1].content)  # task b saw A's number re-used

        # Only the synthesis streams as text; the subagents' own text never becomes parts.
        assert result.types.count("start-step") == 1
        text = "".join(str(chunk["delta"]) for chunk in result.of_type("text-delta"))
        assert text.startswith("# A or B")
        assert [step.kind for step in result.steps] == ["assistant"]
        synthesis_prompt = str(models.lead.calls[0][-1].content)
        assert "[1] A docs — https://a.example/" in synthesis_prompt
        assert "### Task a (done)" in synthesis_prompt

        # Citation check: the checker's verdict plus the numbers that do not exist.
        citations = result.of_type("data-research-citations")
        assert citations == [
            {
                "type": "data-research-citations",
                "id": "citations",
                "data": {"unsupported": ["B is cheap"], "unknownNumbers": [9]},
            }
        ]

        # Usage sums every model call: planner (1) + subagents (4) + synthesis (1) + checker (1).
        assert result.finished.usage.total.total_tokens == 7 * 15
        assert set(result.finished.usage.by_model) == {"plan", "research_task", "scripted", "citation_check"}
        assert result.finished.stop.reason == "end"
        assert result.types[-1] == "finish"
        parts = [part["type"] for part in result.finished.parts]
        assert parts[0] == "data-research-plan"
        assert parts.count("data-research-task") == 2
        assert parts[-1] == "data-research-citations"


class TestDegradedPaths:
    async def test_a_failed_task_still_synthesizes(self) -> None:
        worker = ScriptedChatModel(turns=worker_turns()[:2])
        worker.failures[2] = AppError.service_unavailable("LLM provider is busy, please retry")
        models = Models(worker=worker, lead=ScriptedChatModel(turns=lead_turns()))
        ctx = make_run_context(search=FakeSearchClient(results=RESULTS))
        result = await _run(_graph(models, SERIAL, with_checker=False), ctx)
        statuses = {str(card["id"]): _data(card)["status"] for card in result.of_type("data-research-task")}
        assert statuses == {"a": "done", "b": "failed"}
        assert "### Task b (failed)\nFailed: LLM provider is busy, please retry" in str(
            models.lead.calls[0][-1].content
        )
        assert result.finished.stop.reason == "end"
        assert result.of_type("data-research-citations") == []

    async def test_token_budget_skips_later_tasks(self) -> None:
        models = Models(worker=ScriptedChatModel(turns=worker_turns()[:2]), lead=ScriptedChatModel(turns=lead_turns()))
        ctx = make_run_context(search=FakeSearchClient(results=RESULTS))
        result = await _run(
            _graph(models, ResearchBudget(max_parallel=1, total_token_budget=20), with_checker=False), ctx
        )
        statuses = {str(card["id"]): _data(card)["status"] for card in result.of_type("data-research-task")}
        assert statuses == {"a": "done", "b": "skipped"}
        assert len(models.worker.calls) == 2
        assert result.finished.stop.reason == "end"

    async def test_no_findings_is_an_error(self) -> None:
        worker = ScriptedChatModel()
        worker.failures[0] = AppError.service_unavailable("down")
        worker.failures[1] = AppError.service_unavailable("down")
        ctx = make_run_context(search=FakeSearchClient(results=RESULTS))
        result = await _run(_graph(Models(worker=worker), SERIAL), ctx)
        assert result.types[-1] == "error"
        assert result.chunks[-1] == {"type": "error", "errorText": "Research produced no findings to synthesize"}
        assert result.finished.stop.reason == "error"
        assert models_calls(result) == 0

    async def test_unparsable_plan_twice_is_an_error(self) -> None:
        planner = ScriptedChatModel(turns=[scripted_turn("I would rather chat."), scripted_turn("still no json")])
        ctx = make_run_context(search=FakeSearchClient(results=RESULTS))
        result = await _run(_graph(Models(planner=planner), SERIAL), ctx)
        assert len(planner.calls) == 2
        assert isinstance(planner.calls[1][-1], HumanMessage)
        assert result.chunks[-1] == {
            "type": "error",
            "errorText": "Could not plan the research; please rephrase the question",
        }
        assert result.of_type("data-research-plan") == []
        assert result.finished.usage.total.total_tokens == 30

    async def test_cancel_aborts(self) -> None:
        ctx = make_run_context(search=FakeSearchClient(results=RESULTS))
        ctx.cancel.request("user")
        result = await _run(_graph(Models(worker=ScriptedChatModel(turns=worker_turns())), SERIAL), ctx)
        assert result.types[-1] == "abort"
        assert result.finished.stop.reason == "cancelled"


def models_calls(result: Research) -> int:
    return len(result.of_type("text-delta"))


class TestPlanParsing:
    def test_parse_and_scale(self) -> None:
        plan = parse_plan("```json\n" + json.dumps(PLAN) + "\n```")
        assert plan is not None
        assert [task.id for task in plan.tasks] == ["a", "b"]
        scaled = scale_plan(plan, ResearchBudget(max_subagents=5, max_tool_calls_per_subagent=12))
        assert [task.max_tool_calls for task in scaled.tasks] == [12, 5]
        simple = scale_plan(ResearchPlan("s", "simple", plan.tasks), ResearchBudget())
        assert len(simple.tasks) == 1
        assert simple.tasks[0].max_tool_calls == 10
        complex_plan = ResearchPlan("c", "complex", tuple(ResearchTask(str(i), str(i), "o", 99) for i in range(8)))
        assert len(scale_plan(complex_plan, ResearchBudget(max_subagents=3)).tasks) == 3

    def test_rejects_malformed_plans_and_dedupes_ids(self) -> None:
        assert parse_plan("no json") is None
        assert parse_plan('{"complexity": "weird", "tasks": []}') is None
        assert parse_plan('{"complexity": "simple", "tasks": []}') is None
        assert parse_plan('{"complexity": "simple", "tasks": [{"objective": ""}]}') is None
        plan = parse_plan(
            '{"complexity": "complex", "tasks": [{"id": "x", "objective": "one"}, {"id": "x", "objective": "two"}]}'
        )
        assert plan is not None
        assert [task.id for task in plan.tasks] == ["x", "x-2"]
        assert plan.tasks[0].max_tool_calls == 8
        assert parse_json_object('prose {"a": 1} trailing') == {"a": 1}
        assert parse_json_object("[1, 2]") is None

    def test_sources_sequence_type(self) -> None:
        tasks: Sequence[ResearchTask] = (ResearchTask("a", "A", "o", 3),)
        assert ResearchPlan("s", "simple", tuple(tasks)).as_data()["tasks"] == [
            {"id": "a", "title": "A", "objective": "o", "status": "pending"}
        ]
