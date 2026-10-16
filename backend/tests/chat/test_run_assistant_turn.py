"""``RunAssistantTurn`` end to end without HTTP: the real graphs with scripted models, the fake
tool clients, tracer and listener, and the worker-side use cases on a ``SessionScope`` bound to the
rolled-back test transaction. Every scenario checks what the client would see (the event log) and
what the next request would load (the run row and the assistant message) agree."""

from __future__ import annotations

import asyncio
import json
from base64 import b64encode
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import AttachmentKind
from app.chat.models import ConversationModel, MessageModel, MessageRole, RunEventModel, RunMode, RunModel, RunStatus
from app.chat.use_cases.run_assistant_turn import RUN_TIMEOUT_TEXT, SHUTDOWN_ERROR, SHUTDOWN_TEXT, RunAssistantTurn
from app.core.agent.checkpointer import Checkpointer, NullCheckpointer
from app.core.agent.graph import agent_input, build_agent_graph, run_config, stream_agent
from app.core.agent.state import AgentLimits
from app.core.agent.stream import StepCompleted, UIChunkEvent, map_graph_stream
from app.core.config import agent_settings, chat_settings, llm_settings, research_settings
from app.core.llm.catalog import model_catalog
from app.core.llm.errors import BUSY
from app.core.llm.history import dump_turn
from app.core.search import SearchResult
from app.core.tools.base import RunContext, ToolBudget
from app.core.tools.registry import default_tool_registry
from app.core.ui_fold import fold_parts
from app.core.ui_stream import UI_CHUNK_ADAPTER, CancelToken, JsonObject, UIChunk
from app.db.listen import RUN_CONTROL_CHANNEL
from app.db.session import SessionScope
from app.organizations.models import OrganizationModel
from app.teams.models import TeamModel
from app.users.models import UserModel
from tests.core.research.test_graph import PLAN, lead_turns, worker_turns
from tests.core.research.test_graph import RESULTS as RESEARCH_RESULTS
from tests.fakes import FakeListener
from tests.fakes_llm import (
    GPT,
    NATIVE_CATALOG,
    OPUS,
    FakeChatModelFactory,
    FakeSearchClient,
    FakeTracer,
    ScriptedChatModel,
    scripted_openai_turn,
    scripted_turn,
)
from tests.sample_files import PNG_1X1
from tests.seeds import (
    seed_attachment,
    seed_conversation,
    seed_message,
    seed_organization,
    seed_run,
    seed_run_events,
    seed_team,
    seed_user,
)

WORKER = "host:1"
QUESTION = "What changed in Python 3.14?"
TITLE = "Python 3.14 Changes"
DOCS_URL = "https://docs.python.org/3.14/whatsnew/"
PEP_URL = "https://peps.python.org/pep-0750/"
RESULTS = {
    "python 3.14": [SearchResult(url=DOCS_URL, title="What's new in 3.14", snippet="adds", published_at=None, score=1)],
    "pep 750": [SearchResult(url=PEP_URL, title="PEP 750", snippet="t-strings", published_at=None, score=0.9)],
}


# ── Scripted models that let a test act mid-stream ───────────────────────────


class PacedChatModel(ScriptedChatModel):
    """Streams with a pause between chunks; can hang or fail at a given (call, chunk) position."""

    pause_s: float = 0.005
    streaming: asyncio.Event = Field(default_factory=asyncio.Event)
    hang_at: tuple[int, int] | None = None
    fail_at: tuple[int, int] | None = None
    failure: Exception | None = None

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        call = len(self.calls)
        emitted = 0
        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
            self.streaming.set()
            if self.fail_at == (call, emitted) and self.failure is not None:
                raise self.failure
            if self.hang_at == (call, emitted):
                await asyncio.sleep(30)
            yield chunk
            emitted += 1
            await asyncio.sleep(self.pause_s)


@dataclass
class MemoryCheckpointer:
    """``Checkpointer`` over LangGraph's in-memory saver: real crash-resume without Postgres."""

    memory: InMemorySaver = field(default_factory=InMemorySaver)
    deleted: list[str] = field(default_factory=list)

    @property
    def saver(self) -> BaseCheckpointSaver[str] | None:
        return self.memory

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)
        await self.memory.adelete_thread(thread_id)


# ── Fixtures and readers ─────────────────────────────────────────────────────


@pytest.fixture
async def owner(db_session: AsyncSession) -> UserModel:
    return await seed_user(db_session, email="owner@example.com", full_name="Org Owner")


@pytest.fixture
async def team(db_session: AsyncSession, owner: UserModel) -> TeamModel:
    organization: OrganizationModel = await seed_organization(db_session, name="Nice Chatbot", owner=owner)
    return await seed_team(db_session, organization=organization, name="Research", creator=owner)


@pytest.fixture
async def conversation(db_session: AsyncSession, team: TeamModel, owner: UserModel) -> ConversationModel:
    conversation = await seed_conversation(db_session, team=team, creator=owner)
    await seed_message(
        db_session,
        conversation=conversation,
        role=MessageRole.USER,
        position=0,
        parts=[{"type": "text", "text": QUESTION}],
        created_by=owner,
    )
    return conversation


@pytest.fixture
async def run(db_session: AsyncSession, conversation: ConversationModel, owner: UserModel) -> RunModel:
    """A run this worker just claimed."""
    return await seed_run(
        db_session,
        conversation=conversation,
        requested_by=owner,
        status=RunStatus.RUNNING,
        worker_id=WORKER,
        heartbeat_at=datetime.now(UTC),
    )


def _title_model() -> ScriptedChatModel:
    return ScriptedChatModel(turns=[scripted_turn(json.dumps({"title": TITLE}))])


def _factory(chat: ScriptedChatModel, **others: ScriptedChatModel) -> FakeChatModelFactory:
    return FakeChatModelFactory(by_purpose={"chat": chat, "title": _title_model(), **others})


@dataclass
class Harness:
    scope: SessionScope
    listener: FakeListener
    tracer: FakeTracer = field(default_factory=FakeTracer)
    # `None`: a server without a search provider (the web tools cannot be offered).
    search: FakeSearchClient | None = field(default_factory=lambda: FakeSearchClient(results=RESULTS))
    checkpointer: Checkpointer = field(default_factory=NullCheckpointer)

    def use_case(self, llm: FakeChatModelFactory) -> RunAssistantTurn:
        return RunAssistantTurn(
            self.scope, llm, default_tool_registry(), self.tracer, self.checkpointer, self.listener, self.search, None
        )


@pytest.fixture
def harness(test_scope: SessionScope, fake_listener: FakeListener) -> Harness:
    return Harness(scope=test_scope, listener=fake_listener)


async def _events(db: AsyncSession, run: RunModel) -> list[UIChunk]:
    result = await db.execute(select(RunEventModel).where(RunEventModel.run_id == run.id).order_by(RunEventModel.seq))
    return [UI_CHUNK_ADAPTER.validate_python(event.payload) for event in result.scalars()]


async def _message(db: AsyncSession, run: RunModel) -> MessageModel:
    result = await db.execute(select(MessageModel).where(MessageModel.run_id == run.id))
    return result.scalar_one()


def _types(chunks: Sequence[UIChunk]) -> list[str]:
    return [chunk["type"] for chunk in chunks]


def _part_types(parts: Sequence[JsonObject]) -> list[str]:
    return [str(part["type"]) for part in parts]


def _text(parts: Sequence[JsonObject]) -> str:
    return "".join(str(part.get("text", "")) for part in parts if part.get("type") == "text")


def _title_chunks(chunks: Sequence[UIChunk]) -> list[dict[str, object]]:
    return [dict(chunk) for chunk in chunks if chunk["type"] == "data-conversation-title"]


async def _wait_for_seq(scope: SessionScope, run: RunModel, minimum: int) -> None:
    """Block until the worker has persisted at least ``minimum`` events of ``run`` (bounded)."""

    async def poll() -> None:
        while True:
            async with scope() as session:
                seq = (await session.execute(select(RunModel.last_seq).where(RunModel.id == run.id))).scalar_one()
            if seq >= minimum:
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), 5)


async def _set_mid_run(scope: SessionScope, run: RunModel, **values: object) -> None:
    """Change the run row while a turn is streaming, through the serialized scope."""
    async with scope() as session:
        for name, value in values.items():
            setattr(run, name, value)
        await session.flush()


# ── Scenarios ────────────────────────────────────────────────────────────────


class TestHappyPath:
    async def test_text_tool_text_is_streamed_persisted_titled_and_traced(
        self, db_session: AsyncSession, harness: Harness, conversation: ConversationModel, run: RunModel
    ) -> None:
        turn_1 = scripted_turn(
            "Let me search.", tool_calls=[("web_search", {"query": "python 3.14"})], input_tokens=100, output_tokens=20
        )
        turn_2 = scripted_turn("Python 3.14 adds t-strings [1].", input_tokens=150, output_tokens=30)
        chat = ScriptedChatModel(turns=[turn_1, turn_2])
        llm = _factory(chat)

        await harness.use_case(llm).execute(run_id=run.id, worker_id=WORKER)

        await db_session.refresh(run)
        message = await _message(db_session, run)
        events = await _events(db_session, run)

        # The run row: terminal, counted, traced.
        assert (run.status, run.error, run.step_count) == ("succeeded", None, 3)
        assert (run.input_tokens, run.output_tokens) == (250, 50)
        assert run.trace_id == harness.tracer.trace_id
        assert run.finished_at is not None
        assert run.last_seq == len(events)

        # The stream: start with the message id, the title just before the terminal chunk.
        assert events[0] == {"type": "start", "messageId": str(message.id)}
        assert events[-1] == {"type": "finish", "finishReason": "stop"}
        assert _title_chunks(events) == [
            {"type": "data-conversation-title", "data": {"title": TITLE}, "transient": True}
        ]
        assert events[-2]["type"] == "data-conversation-title"

        # The message mirrors the stream exactly.
        assert _part_types(message.parts) == [
            "step-start",
            "text",
            "tool-web_search",
            "source-url",
            "step-start",
            "text",
        ]
        assert message.parts == fold_parts(events)
        tool = message.parts[2]
        assert (tool["state"], tool["input"]) == ("output-available", {"query": "python 3.14"})
        assert message.parts[3] == {
            "type": "source-url",
            "sourceId": "1",
            "url": DOCS_URL,
            "title": "What's new in 3.14",
        }
        assert message.parts[-1]["text"] == "Python 3.14 adds t-strings [1]."
        assert (message.input_tokens, message.output_tokens) == (250, 50)
        assert (message.provider, message.model) == ("anthropic", OPUS.id)
        # `provider_messages` is the turn's LangChain messages as `dumpd` writes them (verbatim replay).
        provider_messages = cast("list[dict[str, object]]", message.provider_messages)
        assert [cast("list[str]", item["id"])[-1] for item in provider_messages] == [
            "AIMessage",
            "ToolMessage",
            "AIMessage",
        ]
        assert all((item["lc"], item["type"]) == (1, "constructor") for item in provider_messages)
        assert provider_messages[1] == dump_turn(_tool_results(chat))[0]

        # The model saw the system prompt for this workspace, the history and the enabled tools.
        system, human = chat.calls[0][0], chat.calls[0][-1]
        assert isinstance(system, SystemMessage)
        assert "Workspace (team): Research" in str(system.content)
        assert "You are talking with: Org Owner" in str(system.content)
        assert "web_fetch, web_search" in str(system.content)
        assert isinstance(human, HumanMessage)
        assert human.content == QUESTION
        assert chat.bound_tools == [["web_fetch", "web_search"], ["web_fetch", "web_search"]]
        assert isinstance(chat.calls[1][-1], ToolMessage)

        # Title: generated from the first user message by the title model, persisted once.
        await db_session.refresh(conversation)
        assert conversation.title == TITLE
        title_builds = [build for build in llm.builds if build["purpose"] == "title"]
        assert len(title_builds) == 1
        assert (title_builds[0]["silent"], title_builds[0]["effort"]) == (True, "low")

        # Tracing: one root context, flushed once.
        [context] = harness.tracer.run_contexts
        assert (context["mode"], context["model"], context["attempt"], context["user_id"]) == (
            "chat",
            OPUS.id,
            1,
            run.requested_by,
        )
        assert harness.tracer.flushes == 1
        assert harness.listener.subscriptions.get((RUN_CONTROL_CHANNEL, str(run.id)), set()) == set()


def _tool_results(model: ScriptedChatModel) -> list[ToolMessage]:
    return [message for message in model.calls[-1] if isinstance(message, ToolMessage)]


class TestToolHonesty:
    """What the prompt promises is what is bound: nothing when the server lacks the capability, the
    provider's built-in search when the model has one."""

    async def test_requested_tools_the_server_cannot_offer_are_declared_unavailable(
        self,
        db_session: AsyncSession,
        test_scope: SessionScope,
        fake_listener: FakeListener,
        run: RunModel,
    ) -> None:
        harness = Harness(scope=test_scope, listener=fake_listener, search=None)
        chat = ScriptedChatModel(turns=[scripted_turn("I cannot search in this conversation.")])

        await harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER)

        await db_session.refresh(run)
        assert (run.status, run.step_count) == ("succeeded", 1)
        message = await _message(db_session, run)
        assert _part_types(message.parts) == ["step-start", "text"]
        # The switch was on (`options.web_search`), but nothing was bound — and the prompt says so.
        assert chat.bound_tools == []
        system = str(chat.calls[0][0].content)
        assert "Tools enabled in this conversation: none" in system
        assert "Requested but unavailable here (say so if asked): web_fetch, web_search" in system
        assert "Citations:" not in system

    async def test_native_search_runs_inside_the_model_call_and_is_persisted(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        test_scope: SessionScope,
        fake_listener: FakeListener,
        conversation: ConversationModel,
        owner: UserModel,
    ) -> None:
        monkeypatch.setattr("app.chat.use_cases.run_assistant_turn.model_catalog", lambda: NATIVE_CATALOG)
        run = await seed_run(
            db_session,
            conversation=conversation,
            requested_by=owner,
            status=RunStatus.RUNNING,
            worker_id=WORKER,
            heartbeat_at=datetime.now(UTC),
            model=GPT.id,
        )
        harness = Harness(scope=test_scope, listener=fake_listener, search=None)
        tracked = f"{DOCS_URL}?utm_source=chatgpt.com"
        link = f"([What's new]({tracked}))"
        answer = f"Python 3.14 adds t-strings {link}."
        start = answer.index(link)
        turn = scripted_openai_turn(
            answer,
            reasoning="Checking the release notes.",
            searches=[("python 3.14", [tracked, PEP_URL])],
            citations=[(tracked, "What's new in 3.14", start, start + len(link))],
            input_tokens=100,
            output_tokens=20,
        )
        chat = ScriptedChatModel(turns=[turn])

        await harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER)

        await db_session.refresh(run)
        message = await _message(db_session, run)
        events = await _events(db_session, run)
        # One model step: the search happened inside it, no tool round.
        assert (run.status, run.error, run.step_count) == ("succeeded", None, 1)
        assert (run.input_tokens, run.output_tokens) == (100, 20)
        assert events[-1] == {"type": "finish", "finishReason": "stop"}
        assert message.parts == fold_parts(events)
        assert _part_types(message.parts) == ["step-start", "reasoning", "tool-web_search", "text", "source-url"]
        search = message.parts[2]
        assert (search["state"], search["providerExecuted"], search["input"]) == (
            "output-available",
            True,
            {"query": "python 3.14"},
        )
        assert str(search["toolCallId"]).startswith("ws_")
        assert message.parts[4] == {
            "type": "source-url",
            "sourceId": "1",
            "url": DOCS_URL,
            "title": "What's new in 3.14",
        }
        assert message.parts[3]["text"] == answer  # the model's own link is the citation
        assert (message.provider, message.model) == ("openai", GPT.id)
        provider_messages = cast("list[dict[str, object]]", message.provider_messages)
        assert [cast("list[str]", item["id"])[-1] for item in provider_messages] == ["AIMessage"]
        stored = cast("dict[str, object]", provider_messages[0]["kwargs"])
        assert "web_search_call" in {
            str(block.get("type")) for block in cast("list[dict[str, object]]", stored["content"])
        }
        # The provider tool was bound, and the prompt described the built-in search.
        assert chat.bound_tools == [["web_search"]]
        system = str(chat.calls[0][0].content)
        assert "Tools enabled in this conversation: web_search (built-in)" in system
        assert "web_fetch" not in system.split("# This conversation")[1]
        assert "Requested but unavailable" not in system
        assert "Citations: built-in search" in system


class TestCancel:
    async def test_cancel_request_mid_stream_aborts_and_keeps_the_partial_text(
        self, db_session: AsyncSession, harness: Harness, run: RunModel
    ) -> None:
        chat = PacedChatModel(turns=[scripted_turn(" ".join(["word"] * 400))])
        task = asyncio.create_task(harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER))
        await asyncio.wait_for(chat.streaming.wait(), 5)
        await _wait_for_seq(harness.scope, run, 4)  # start, start-step, text-start and some text

        await _set_mid_run(harness.scope, run, cancel_requested_at=datetime.now(UTC))
        harness.listener.notify(RUN_CONTROL_CHANNEL, f"{run.id}:cancel")
        await asyncio.wait_for(task, 5)

        await db_session.refresh(run)
        message = await _message(db_session, run)
        events = await _events(db_session, run)
        assert (run.status, run.error) == ("cancelled", None)
        assert events[-1] == {"type": "abort", "reason": "cancelled"}
        assert _title_chunks(events) != []
        assert len(chat.calls) == 1
        text = _text(message.parts)
        assert text.startswith("word word")
        assert len(text.split()) < 400
        assert message.parts == fold_parts(events)


class TestProviderFailure:
    async def test_mid_stream_provider_error_fails_the_run_with_the_partial_text(
        self, db_session: AsyncSession, harness: Harness, run: RunModel
    ) -> None:
        chat = PacedChatModel(
            turns=[scripted_turn("Hello there friend")], fail_at=(0, 2), failure=ModelRateLimitError("slow down")
        )

        await harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER)

        await db_session.refresh(run)
        message = await _message(db_session, run)
        events = await _events(db_session, run)
        assert (run.status, run.error) == ("failed", BUSY)
        assert events[-1] == {"type": "error", "errorText": BUSY}
        assert _types(events)[-3:] == ["finish-step", "data-conversation-title", "error"]
        assert _part_types(message.parts) == ["step-start", "text"]
        assert message.parts[1] == {"type": "text", "text": "Hello there ", "state": "done"}
        assert message.parts == fold_parts(events)

    async def test_an_unconfigured_model_fails_before_the_graph_starts(
        self, db_session: AsyncSession, harness: Harness, run: RunModel
    ) -> None:
        run.model = "anthropic:claude-unknown-9"
        await db_session.flush()

        await harness.use_case(_factory(ScriptedChatModel())).execute(run_id=run.id, worker_id=WORKER)

        await db_session.refresh(run)
        events = await _events(db_session, run)
        assert (run.status, run.error) == ("failed", "Unknown model")
        assert _types(events) == ["start", "data-conversation-title", "error"]


class TestStepLimit:
    async def test_the_last_permitted_model_call_has_no_tools_and_answers(
        self, db_session: AsyncSession, harness: Harness, run: RunModel, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(agent_settings, "agent_max_model_calls", 3)
        chat = ScriptedChatModel(
            turns=[
                scripted_turn(tool_calls=[("web_search", {"query": "python 3.14"})]),
                scripted_turn(tool_calls=[("web_search", {"query": "pep 750"})]),
                scripted_turn("Out of tool calls: t-strings [1][2]."),
            ]
        )

        await harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER)

        await db_session.refresh(run)
        message = await _message(db_session, run)
        events = await _events(db_session, run)
        assert (run.status, run.step_count) == ("succeeded", 5)
        assert events[-1] == {"type": "finish", "finishReason": "stop"}
        assert chat.bound_tools == [["web_fetch", "web_search"], ["web_fetch", "web_search"]]
        assert len(chat.calls) == 3
        assert [part["sourceId"] for part in message.parts if part["type"] == "source-url"] == ["1", "2"]
        assert message.parts[-1]["text"] == "Out of tool calls: t-strings [1][2]."


class TestShutdown:
    async def test_cancelling_the_task_fails_the_run_with_the_partial_message(
        self, db_session: AsyncSession, harness: Harness, run: RunModel
    ) -> None:
        chat = PacedChatModel(turns=[scripted_turn(" ".join(["token"] * 400))])
        task = asyncio.create_task(harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER))
        await asyncio.wait_for(chat.streaming.wait(), 5)
        await _wait_for_seq(harness.scope, run, 4)  # start, start-step, text-start and some text

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await db_session.refresh(run)
        message = await _message(db_session, run)
        events = await _events(db_session, run)
        assert (run.status, run.error) == ("failed", SHUTDOWN_ERROR)
        assert events[-1] == {"type": "error", "errorText": SHUTDOWN_TEXT}
        assert _text(message.parts).startswith("token token")
        assert message.parts == fold_parts(events)
        assert harness.tracer.flushes == 1

    async def test_the_wall_clock_fails_a_run_that_takes_too_long(
        self, db_session: AsyncSession, harness: Harness, run: RunModel, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(chat_settings, "chat_run_timeout_s", 0.2)
        chat = PacedChatModel(turns=[scripted_turn("slow answer")], hang_at=(0, 1))

        await harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER)

        await db_session.refresh(run)
        events = await _events(db_session, run)
        assert (run.status, run.error) == ("failed", RUN_TIMEOUT_TEXT)
        assert events[-1] == {"type": "error", "errorText": RUN_TIMEOUT_TEXT}
        assert _text((await _message(db_session, run)).parts) == "slow "


class TestLeaseLost:
    async def test_a_lost_lease_stops_the_turn_without_another_write(
        self, db_session: AsyncSession, harness: Harness, run: RunModel
    ) -> None:
        chat = PacedChatModel(turns=[scripted_turn(" ".join(["word"] * 400))])
        task = asyncio.create_task(harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER))
        await asyncio.wait_for(chat.streaming.wait(), 5)
        await _wait_for_seq(harness.scope, run, 4)  # start, start-step, text-start and some text

        # The reaper re-queued the run and another worker claimed it.
        await _set_mid_run(harness.scope, run, worker_id="host:2", attempt=2)
        async with harness.scope() as session:
            seq_at_loss = (await session.execute(select(RunModel.last_seq).where(RunModel.id == run.id))).scalar_one()
        harness.listener.notify(RUN_CONTROL_CHANNEL, f"{run.id}:cancel")
        await asyncio.wait_for(task, 5)

        await db_session.refresh(run)
        events = await _events(db_session, run)
        assert (run.status, run.worker_id, run.finished_at) == ("running", "host:2", None)
        assert run.last_seq == seq_at_loss == len(events) >= 4
        assert events[-1]["type"] not in {"abort", "error", "finish"}
        assert harness.tracer.flushes == 1


class TestResume:
    async def test_attempt_two_resumes_the_checkpoint_and_keeps_completed_steps(
        self,
        db_session: AsyncSession,
        test_scope: SessionScope,
        fake_listener: FakeListener,
        conversation: ConversationModel,
        owner: UserModel,
    ) -> None:
        conversation.title = "Resumed"
        await db_session.flush()
        run = await seed_run(
            db_session,
            conversation=conversation,
            requested_by=owner,
            status=RunStatus.RUNNING,
            worker_id=WORKER,
            attempt=2,
            heartbeat_at=datetime.now(UTC),
        )
        run.trace_id = "f" * 32
        await db_session.flush()
        checkpointer = MemoryCheckpointer()
        search = FakeSearchClient(results=RESULTS)

        # Attempt 1 (on a worker that then died): one tool round completed, the second model
        # step interrupted mid-text. Its chunks and completed steps are what it left in Postgres.
        chunks_1, steps_1 = await _crashed_first_attempt(run, checkpointer, search)
        assert _types(chunks_1)[-4:] == ["start-step", "text-start", "text-delta", "text-delta"]
        start: UIChunk = {"type": "start", "messageId": "placeholder"}
        await seed_run_events(db_session, run, [start, *chunks_1])
        last_step = steps_1[-1]
        provider_messages = dump_turn([message for step in steps_1 for message in step.messages])
        await seed_message(
            db_session,
            conversation=conversation,
            role=MessageRole.ASSISTANT,
            position=1,
            parts=list(last_step.parts),
            run=run,
            provider_messages=provider_messages,
            input_tokens=100,
            output_tokens=20,
        )
        assert _part_types(last_step.parts) == ["step-start", "text", "tool-web_search", "source-url"]
        seq_before = run.last_seq

        # Attempt 2: this worker.
        chat_2 = ScriptedChatModel(
            turns=[
                scripted_turn("One more.", tool_calls=[("web_search", {"query": "pep 750"})], input_tokens=50),
                scripted_turn("The answer: t-strings [1][2].", input_tokens=60, output_tokens=7),
            ]
        )
        tracer = FakeTracer()
        harness = Harness(
            scope=test_scope, listener=fake_listener, tracer=tracer, search=search, checkpointer=checkpointer
        )
        await harness.use_case(_factory(chat_2)).execute(run_id=run.id, worker_id=WORKER)

        await db_session.refresh(run)
        message = await _message(db_session, run)
        events = await _events(db_session, run)
        new_events = events[seq_before:]

        # The stream continues the log: reset the interrupted step, no second `start`.
        assert new_events[0] == {"type": "reset-step"}
        assert "start" not in _types(new_events)
        assert events[-1] == {"type": "finish", "finishReason": "stop"}
        assert run.last_seq == len(events)
        # The graph resumed from the checkpoint: the model saw the tool result, not the prompt again.
        assert len(chat_2.calls) == 2
        assert isinstance(chat_2.calls[0][-1], ToolMessage)
        # Completed parts kept, the partial text dropped, sources numbered on from [1].
        assert _part_types(message.parts) == [
            "step-start",
            "text",
            "tool-web_search",
            "source-url",
            "step-start",
            "text",
            "tool-web_search",
            "source-url",
            "step-start",
            "text",
        ]
        assert message.parts[:4] == list(last_step.parts)
        assert [part["sourceId"] for part in message.parts if part["type"] == "source-url"] == ["1", "2"]
        assert message.parts[-1]["text"] == "The answer: t-strings [1][2]."
        assert "The answer " not in _text(message.parts[4:6])
        assert message.parts == fold_parts(events)
        assert len(cast("list[object]", message.provider_messages)) == len(provider_messages) + 3
        assert (message.input_tokens, message.output_tokens) == (100 + 110, 20 + 12)
        # The run row: finished, usage on top of attempt 1, trace kept, step count across attempts.
        assert (run.status, run.attempt, run.trace_id) == ("succeeded", 2, "f" * 32)
        assert (run.input_tokens, run.output_tokens, run.step_count) == (210, 32, 4)
        assert tracer.run_contexts[0]["attempt"] == 2
        assert checkpointer.deleted == [str(run.id)]
        assert _title_chunks(events) == []


async def _crashed_first_attempt(
    run: RunModel, checkpointer: MemoryCheckpointer, search: FakeSearchClient
) -> tuple[list[UIChunk], list[StepCompleted]]:
    """Run the real graph for ``run``'s thread until a hang in its second model step, then cut it off."""
    chat_1 = PacedChatModel(
        turns=[
            scripted_turn("Looking.", tool_calls=[("web_search", {"query": "python 3.14"})]),
            scripted_turn("The answer is coming."),
        ],
        hang_at=(1, 2),
    )
    assert run.requested_by is not None
    ctx = RunContext(
        run_id=run.id,
        conversation_id=run.conversation_id,
        user_id=run.requested_by,
        team_id=run.conversation_id,
        attempt=1,
        cancel=CancelToken(),
        tracer=FakeTracer(),
        budget=ToolBudget(max_tool_calls=24),
        search=search,
    )
    built = FakeChatModelFactory(by_purpose={"chat": chat_1}).build(OPUS, effort="medium", purpose="chat")
    tools = default_tool_registry().for_run(ctx, names={"web_search"}, spec=OPUS)
    graph = build_agent_graph(built, tools, AgentLimits(), checkpointer=checkpointer.saver, name="chat")
    config = run_config(thread_id=str(run.id))
    prompt = [SystemMessage(content="sys"), HumanMessage(content=QUESTION)]
    chunks: list[UIChunk] = []
    steps: list[StepCompleted] = []

    async def drive() -> None:
        async for event in map_graph_stream(stream_agent(graph, agent_input(prompt), config, ctx=ctx), ctx=ctx):
            if isinstance(event, UIChunkEvent):
                chunks.append(event.chunk)
            elif isinstance(event, StepCompleted):
                steps.append(event)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(drive(), 0.5)
    return chunks, steps


class TestDeepResearch:
    async def test_research_mode_plans_delegates_synthesizes_and_checks_citations(
        self,
        db_session: AsyncSession,
        test_scope: SessionScope,
        fake_listener: FakeListener,
        conversation: ConversationModel,
        owner: UserModel,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(research_settings, "research_max_parallel", 1)
        run = await seed_run(
            db_session,
            conversation=conversation,
            requested_by=owner,
            status=RunStatus.RUNNING,
            mode=RunMode.DEEP_RESEARCH,
            worker_id=WORKER,
            heartbeat_at=datetime.now(UTC),
        )
        planner = ScriptedChatModel(turns=[scripted_turn(json.dumps(PLAN))])
        worker = ScriptedChatModel(turns=worker_turns())
        lead = ScriptedChatModel(turns=lead_turns())
        checker = ScriptedChatModel(turns=[scripted_turn('{"unsupported": ["B is cheap"]}')])
        llm = FakeChatModelFactory(
            by_purpose={
                "research_plan": planner,
                "research_task": worker,
                "research_synthesis": lead,
                "research_citations": checker,
                "title": _title_model(),
            }
        )
        tracer = FakeTracer()
        harness = Harness(
            scope=test_scope, listener=fake_listener, tracer=tracer, search=FakeSearchClient(results=RESEARCH_RESULTS)
        )

        await harness.use_case(llm).execute(run_id=run.id, worker_id=WORKER)

        await db_session.refresh(run)
        message = await _message(db_session, run)
        events = await _events(db_session, run)
        assert (run.status, run.error) == ("succeeded", None)
        assert (run.input_tokens, run.output_tokens) == (70, 35)
        assert events[0]["type"] == "start"
        assert events[-1] == {"type": "finish", "finishReason": "stop"}
        assert _title_chunks(events) != []
        types = _part_types(message.parts)
        assert types[0] == "data-research-plan"
        assert types.count("data-research-task") == 2
        assert types.count("source-url") == 2
        assert types[-1] == "data-research-citations"
        assert "text" in types
        assert _text(message.parts).startswith("# A or B")
        assert message.parts == fold_parts(events)
        # The question is the latest user message; the planner saw it.
        assert f"Question:\n{QUESTION}" in str(planner.calls[0][-1].content)
        purposes = {build["purpose"] for build in llm.builds}
        assert purposes == {"research_plan", "research_task", "research_synthesis", "research_citations", "title"}
        assert tracer.run_contexts[0]["mode"] == "deep_research"


class TestNotLeased:
    async def test_a_run_owned_by_another_worker_is_skipped(
        self, db_session: AsyncSession, harness: Harness, run: RunModel
    ) -> None:
        chat = ScriptedChatModel(turns=[scripted_turn("never")])

        await harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id="host:2")

        await db_session.refresh(run)
        assert (run.status, run.worker_id, run.last_seq) == ("running", WORKER, 0)
        assert chat.calls == []
        assert harness.tracer.run_contexts == []


# ── Attachments ──────────────────────────────────────────────────────────────

LOCAL_MODEL = "openai:llama3.3"


@pytest.fixture
def local_model(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A local OpenAI-compatible model in the process catalog (the suite's settings list only
    Claude), configured as a server that cannot see images (``LLM_OPENAI_SUPPORTS_VISION=false``)."""
    monkeypatch.setattr(llm_settings, "openai_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(llm_settings, "llm_openai_supports_vision", False)
    monkeypatch.setattr(llm_settings, "llm_models", [*llm_settings.llm_models, LOCAL_MODEL])
    model_catalog.cache_clear()
    yield LOCAL_MODEL
    monkeypatch.undo()
    model_catalog.cache_clear()


async def _conversation_with_files(
    db: AsyncSession, team: TeamModel, owner: UserModel, *, text: str
) -> tuple[ConversationModel, MessageModel]:
    """A titled conversation whose one user message carries a PNG and a Markdown file."""
    conversation = await seed_conversation(db, team=team, creator=owner, title="Files")
    message = await seed_message(
        db, conversation=conversation, role=MessageRole.USER, position=0, parts=[], created_by=owner
    )
    chart = await seed_attachment(
        db,
        team=team,
        uploader=owner,
        filename="chart.png",
        media_type="image/png",
        kind=AttachmentKind.IMAGE,
        data=PNG_1X1,
        extracted_text=None,
        message=message,
    )
    notes = await seed_attachment(
        db,
        team=team,
        uploader=owner,
        filename="notes.md",
        media_type="text/markdown",
        extracted_text="# Plan\nShip it",
        message=message,
    )
    parts: list[JsonObject] = [{"type": "text", "text": text}] if text else []
    for attachment in (chart, notes):
        parts.append(
            {
                "type": "file",
                "mediaType": attachment.media_type,
                "filename": attachment.filename,
                "url": attachment.url,
                "attachmentId": str(attachment.id),
            }
        )
    message.parts = parts
    await db.flush()
    return conversation, message


NOTES_BLOCK = {
    "type": "text",
    "text": '<attachment name="notes.md" type="text/markdown" chars="14">\n# Plan\nShip it\n</attachment>',
}


def _human_content(chat: ScriptedChatModel) -> list[dict[str, object]]:
    human = chat.calls[0][-1]
    assert isinstance(human, HumanMessage)
    assert isinstance(human.content, list)
    return cast("list[dict[str, object]]", human.content)


class TestAttachments:
    async def test_a_vision_model_sees_the_image_and_the_text_file_as_blocks(
        self, db_session: AsyncSession, harness: Harness, team: TeamModel, owner: UserModel
    ) -> None:
        conversation, _ = await _conversation_with_files(db_session, team, owner, text="What do these say?")
        run = await seed_run(
            db_session, conversation=conversation, requested_by=owner, status=RunStatus.RUNNING, worker_id=WORKER
        )
        chat = ScriptedChatModel(turns=[scripted_turn("A chart and a plan.")])

        await harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER)

        content = _human_content(chat)
        assert content[0] == {"type": "text", "text": "What do these say?"}
        assert (content[1]["type"], content[1]["mime_type"], content[1]["base64"]) == (
            "image",
            "image/png",
            b64encode(PNG_1X1).decode(),
        )
        assert content[2] == NOTES_BLOCK
        await db_session.refresh(run)
        assert run.status == "succeeded"
        assert _text((await _message(db_session, run)).parts) == "A chart and a plan."

    async def test_a_model_without_vision_gets_a_placeholder_for_the_image(
        self, db_session: AsyncSession, harness: Harness, team: TeamModel, owner: UserModel, local_model: str
    ) -> None:
        conversation, _ = await _conversation_with_files(db_session, team, owner, text="")
        run = await seed_run(
            db_session,
            conversation=conversation,
            requested_by=owner,
            status=RunStatus.RUNNING,
            model=local_model,
            worker_id=WORKER,
        )
        chat = ScriptedChatModel(turns=[scripted_turn("I can read the notes.")])

        await harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER)

        content = _human_content(chat)
        assert content == [
            {"type": "text", "text": "[image attached: chart.png — this model cannot view images]"},
            NOTES_BLOCK,
        ]
        await db_session.refresh(run)
        assert (run.status, run.provider) == ("succeeded", "openai")

    async def test_a_message_without_attachments_keeps_plain_string_content(
        self, harness: Harness, run: RunModel
    ) -> None:
        chat = ScriptedChatModel(turns=[scripted_turn("Plain.")])

        await harness.use_case(_factory(chat)).execute(run_id=run.id, worker_id=WORKER)

        human = chat.calls[0][-1]
        assert isinstance(human, HumanMessage)
        assert human.content == QUESTION
