"""The worker's dispatch loop in-process: claim → run → terminal, the reaper feeding it a lost
run, and a shutdown that closes the turns it was running. ``Worker`` takes its collaborators, so
nothing global is patched; the queue wake-ups come from the ``FakeListener``."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ConversationModel, MessageModel, MessageRole, RunEventModel, RunModel, RunStatus
from app.chat.use_cases.run_assistant_turn import SHUTDOWN_ERROR
from app.core.agent.checkpointer import NullCheckpointer
from app.core.tools.registry import default_tool_registry
from app.db.listen import RUN_QUEUE_CHANNEL
from app.db.session import SessionScope
from app.organizations.models import OrganizationModel
from app.teams.models import TeamModel
from app.users.models import UserModel
from app.worker import Worker, WorkerDeps, WorkerOptions
from tests.chat.test_run_assistant_turn import PacedChatModel
from tests.fakes import FakeListener
from tests.fakes_llm import FakeChatModelFactory, FakeSearchClient, FakeTracer, ScriptedChatModel, scripted_turn
from tests.seeds import seed_conversation, seed_message, seed_organization, seed_run, seed_team, seed_user

WORKER = "test-host:7"
OPTIONS = WorkerOptions(concurrency=2, poll_interval_s=0.05, reaper_interval_s=0.1, shutdown_grace_s=5)


@pytest.fixture
async def owner(db_session: AsyncSession) -> UserModel:
    return await seed_user(db_session, email="owner@example.com", full_name="Org Owner")


@pytest.fixture
async def team(db_session: AsyncSession, owner: UserModel) -> TeamModel:
    organization: OrganizationModel = await seed_organization(db_session, name="Nice Chatbot", owner=owner)
    return await seed_team(db_session, organization=organization, name="Ops", creator=owner)


async def _conversation(db: AsyncSession, team: TeamModel, owner: UserModel, text: str) -> ConversationModel:
    conversation = await seed_conversation(db, team=team, creator=owner, title="Titled")
    await seed_message(
        db, conversation=conversation, role=MessageRole.USER, position=0, parts=[{"type": "text", "text": text}]
    )
    return conversation


def _deps(scope: SessionScope, listener: FakeListener, chat: ScriptedChatModel) -> WorkerDeps:
    return WorkerDeps(
        sessions=scope,
        listener=listener,
        llm=FakeChatModelFactory(by_purpose={"chat": chat, "title": ScriptedChatModel()}),
        tools=default_tool_registry(),
        tracer=FakeTracer(),
        checkpointer=NullCheckpointer(),
        search=FakeSearchClient(),
        sandbox=None,
    )


async def _wait_until(scope: SessionScope, predicate: Callable[[list[str]], bool], run_ids: list[object]) -> None:
    """Poll the run statuses through the serialized scope until ``predicate`` holds (bounded)."""

    async def poll() -> None:
        while True:
            async with scope() as session:
                rows = await session.execute(select(RunModel.id, RunModel.status).where(RunModel.id.in_(run_ids)))
                statuses = {row[0]: row[1] for row in rows}
            if predicate([statuses[run_id] for run_id in run_ids]):
                return
            await asyncio.sleep(0.02)

    await asyncio.wait_for(poll(), 10)


async def _events(db: AsyncSession, run: RunModel) -> list[str]:
    result = await db.execute(
        select(RunEventModel.type).where(RunEventModel.run_id == run.id).order_by(RunEventModel.seq)
    )
    return list(result.scalars())


class TestServe:
    async def test_claims_queued_and_reaped_runs_then_stops(
        self,
        db_session: AsyncSession,
        test_scope: SessionScope,
        fake_listener: FakeListener,
        team: TeamModel,
        owner: UserModel,
    ) -> None:
        queued_conversation = await _conversation(db_session, team, owner, "first")
        queued = await seed_run(db_session, conversation=queued_conversation, requested_by=owner)
        lost_conversation = await _conversation(db_session, team, owner, "second")
        lost = await seed_run(
            db_session,
            conversation=lost_conversation,
            requested_by=owner,
            status=RunStatus.RUNNING,
            worker_id="dead:1",
            heartbeat_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        chat = ScriptedChatModel(turns=[scripted_turn("answer one"), scripted_turn("answer two")])
        stop = asyncio.Event()
        worker = Worker(WORKER, _deps(test_scope, fake_listener, chat), stop=stop, options=OPTIONS)

        serving = asyncio.create_task(worker.serve())
        await _wait_until(test_scope, lambda statuses: statuses == ["succeeded", "succeeded"], [queued.id, lost.id])
        stop.set()
        fake_listener.notify(RUN_QUEUE_CHANNEL, "wake")
        await asyncio.wait_for(serving, 5)

        await db_session.refresh(queued)
        await db_session.refresh(lost)
        assert (queued.worker_id, queued.attempt) == (WORKER, 1)
        # The reaper re-queued the lost run and this worker ran it as attempt 2 from scratch.
        assert (lost.worker_id, lost.attempt, lost.error) == (WORKER, 2, None)
        for run in (queued, lost):
            events = await _events(db_session, run)
            assert (events[0], events[-1]) == ("start", "finish")
            message = (await db_session.execute(select(MessageModel).where(MessageModel.run_id == run.id))).scalar_one()
            assert message.parts[-1]["text"] in {"answer one", "answer two"}
        assert len(chat.calls) == 2

    async def test_stopping_mid_run_fails_the_turn_within_the_grace_period(
        self,
        db_session: AsyncSession,
        test_scope: SessionScope,
        fake_listener: FakeListener,
        team: TeamModel,
        owner: UserModel,
    ) -> None:
        conversation = await _conversation(db_session, team, owner, "slow one")
        run = await seed_run(db_session, conversation=conversation, requested_by=owner)
        chat = PacedChatModel(turns=[scripted_turn(" ".join(["w"] * 500))])
        stop = asyncio.Event()
        worker = Worker(WORKER, _deps(test_scope, fake_listener, chat), stop=stop, options=OPTIONS)

        serving = asyncio.create_task(worker.serve())
        await asyncio.wait_for(chat.streaming.wait(), 5)
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(serving, 5)

        await db_session.refresh(run)
        assert (run.status, run.error, run.worker_id) == ("failed", SHUTDOWN_ERROR, WORKER)
        assert (await _events(db_session, run))[-1] == "error"
