"""The Postgres-backed run queue as the worker drives it: claiming, the lease fence, the event
log, the assistant message, finishing, the reaper and the one-active-run index. No HTTP — the
worker-side use cases run through a ``SessionScope`` bound to the rolled-back test transaction."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ConversationModel, MessageModel, MessageRole, RunEventModel, RunModel, RunStatus
from app.chat.use_cases.claim_run import ClaimRun
from app.chat.use_cases.finish_run import FinishRun
from app.chat.use_cases.reap_stale_runs import INTERRUPTED_TEXT, ReapStaleRuns
from app.chat.use_cases.record_run_events import RecordRunEvents
from app.chat.use_cases.save_assistant_message import SaveAssistantMessage
from app.chat.use_cases.touch_run import RunLease, TouchRun
from app.core.exceptions import AppError
from app.core.ui_fold import fold_parts
from app.db.session import SessionScope
from app.organizations.models import OrganizationModel
from app.teams.models import TeamModel
from app.users.models import UserModel
from tests.core.test_ui_stream import CANONICAL
from tests.seeds import (
    seed_conversation,
    seed_message,
    seed_organization,
    seed_run,
    seed_run_events,
    seed_team,
    seed_user,
)

WORKER = "host:1"
OTHER_WORKER = "host:2"


@pytest.fixture
async def owner(db_session: AsyncSession) -> UserModel:
    return await seed_user(db_session, email="owner@example.com")


@pytest.fixture
async def team(db_session: AsyncSession, owner: UserModel) -> TeamModel:
    organization: OrganizationModel = await seed_organization(db_session, name="Nice Chatbot", owner=owner)
    return await seed_team(db_session, organization=organization, name="Research", creator=owner)


@pytest.fixture
async def conversation(db_session: AsyncSession, team: TeamModel, owner: UserModel) -> ConversationModel:
    conversation = await seed_conversation(db_session, team=team, creator=owner)
    await seed_message(db_session, conversation=conversation, role=MessageRole.USER, position=0, created_by=owner)
    return conversation


@pytest.fixture
async def queued(db_session: AsyncSession, conversation: ConversationModel, owner: UserModel) -> RunModel:
    return await seed_run(db_session, conversation=conversation, requested_by=owner)


async def _events(db: AsyncSession, run: RunModel) -> list[tuple[int, str]]:
    result = await db.execute(select(RunEventModel).where(RunEventModel.run_id == run.id).order_by(RunEventModel.seq))
    return [(event.seq, event.type) for event in result.scalars()]


async def _assistant_message(db: AsyncSession, run: RunModel) -> MessageModel | None:
    result = await db.execute(select(MessageModel).where(MessageModel.run_id == run.id))
    return result.scalar_one_or_none()


class TestClaim:
    async def test_claims_oldest_first_then_nothing(
        self, db_session: AsyncSession, sessions: SessionScope, team: TeamModel, owner: UserModel
    ) -> None:
        base = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
        runs: list[RunModel] = []
        for minutes in (2, 0, 1):  # seeded out of order on purpose
            conversation = await seed_conversation(db_session, team=team, creator=owner)
            runs.append(
                await seed_run(
                    db_session,
                    conversation=conversation,
                    requested_by=owner,
                    created_at=base + timedelta(minutes=minutes),
                )
            )
        claim = ClaimRun(sessions)

        claimed = [await claim.execute(worker_id=WORKER) for _ in range(4)]

        assert [run.id if run is not None else None for run in claimed] == [runs[1].id, runs[2].id, runs[0].id, None]
        first = claimed[0]
        assert first is not None
        assert (first.status, first.worker_id) == ("running", WORKER)
        assert first.heartbeat_at is not None
        assert first.started_at == first.heartbeat_at


class TestTouch:
    async def test_reports_the_lease_and_cancel_requests(
        self, db_session: AsyncSession, sessions: SessionScope, queued: RunModel
    ) -> None:
        await ClaimRun(sessions).execute(worker_id=WORKER)
        touch = TouchRun(sessions)

        assert await touch.execute(run_id=queued.id, worker_id=WORKER) == RunLease(owned=True, cancel_requested=False)
        assert await touch.execute(run_id=queued.id, worker_id=OTHER_WORKER) == RunLease(
            owned=False, cancel_requested=False
        )

        await db_session.refresh(queued)
        queued.cancel_requested_at = datetime.now(UTC)
        await db_session.flush()

        assert await touch.execute(run_id=queued.id, worker_id=WORKER) == RunLease(owned=True, cancel_requested=True)


class TestRecordEvents:
    async def test_appends_batches_in_sequence_and_fences_on_the_lease(
        self, db_session: AsyncSession, sessions: SessionScope, queued: RunModel
    ) -> None:
        await ClaimRun(sessions).execute(worker_id=WORKER)
        record = RecordRunEvents(sessions)

        assert await record.execute(run_id=queued.id, worker_id=WORKER, chunks=CANONICAL[:3]) == 3
        assert await record.execute(run_id=queued.id, worker_id=WORKER, chunks=[]) == 3
        assert await record.execute(run_id=queued.id, worker_id=WORKER, chunks=CANONICAL[3:5]) == 5

        assert await _events(db_session, queued) == [(seq, chunk["type"]) for seq, chunk in enumerate(CANONICAL[:5], 1)]
        await db_session.refresh(queued)
        assert queued.last_seq == 5

        with pytest.raises(AppError) as lost:
            await record.execute(run_id=queued.id, worker_id=OTHER_WORKER, chunks=CANONICAL[5:6])
        assert lost.value.status_code == 409
        assert len(await _events(db_session, queued)) == 5


class TestSaveAssistantMessage:
    async def test_creates_once_then_replaces_only_what_is_passed(
        self, sessions: SessionScope, queued: RunModel
    ) -> None:
        await ClaimRun(sessions).execute(worker_id=WORKER)
        save = SaveAssistantMessage(sessions)

        created = await save.execute(run_id=queued.id, worker_id=WORKER)

        assert (created.role, created.position, created.parts, created.run_id) == ("assistant", 1, [], queued.id)
        assert (created.provider, created.model) == ("anthropic", "anthropic:claude-opus-5-5")

        parts = fold_parts(CANONICAL[:6])
        updated = await save.execute(
            run_id=queued.id, worker_id=WORKER, parts=parts, provider_messages=[{"type": "ai"}], input_tokens=12
        )

        assert updated.id == created.id
        assert (updated.parts, updated.provider_messages, updated.input_tokens, updated.output_tokens) == (
            parts,
            [{"type": "ai"}],
            12,
            None,
        )
        reused = await save.execute(run_id=queued.id, worker_id=WORKER, output_tokens=40)
        assert (reused.id, reused.parts, reused.input_tokens, reused.output_tokens) == (created.id, parts, 12, 40)

        with pytest.raises(AppError) as lost:
            await save.execute(run_id=queued.id, worker_id=OTHER_WORKER, parts=[])
        assert lost.value.status_code == 409


class TestFinish:
    async def test_closes_the_run_and_bumps_the_conversation(
        self, db_session: AsyncSession, sessions: SessionScope, conversation: ConversationModel, queued: RunModel
    ) -> None:
        before = conversation.last_message_at
        await ClaimRun(sessions).execute(worker_id=WORKER)

        finished = await FinishRun(sessions).execute(
            run_id=queued.id,
            worker_id=WORKER,
            status=RunStatus.SUCCEEDED,
            step_count=2,
            input_tokens=10,
            output_tokens=20,
        )

        assert (finished.status, finished.error, finished.step_count) == ("succeeded", None, 2)
        assert (finished.input_tokens, finished.output_tokens) == (10, 20)
        assert finished.finished_at is not None
        await db_session.refresh(conversation)
        assert conversation.last_message_at > before

        with pytest.raises(AppError) as again:
            await FinishRun(sessions).execute(run_id=queued.id, worker_id=WORKER, status=RunStatus.FAILED, error="x")
        assert again.value.status_code == 409

    async def test_rejects_a_non_terminal_status(self, sessions: SessionScope, queued: RunModel) -> None:
        with pytest.raises(AppError) as rejected:
            await FinishRun(sessions).execute(run_id=queued.id, worker_id=WORKER, status=RunStatus.RUNNING)
        assert rejected.value.status_code == 400


class TestReaper:
    async def test_requeues_a_first_loss_then_fails_a_second_with_the_log_folded(
        self,
        db_session: AsyncSession,
        sessions: SessionScope,
        team: TeamModel,
        conversation: ConversationModel,
        owner: UserModel,
    ) -> None:
        stale_at = datetime.now(UTC) - timedelta(minutes=2)
        lost = await seed_run(
            db_session,
            conversation=conversation,
            requested_by=owner,
            status=RunStatus.RUNNING,
            worker_id="dead:1",
            heartbeat_at=stale_at,
        )
        await seed_run_events(db_session, lost, CANONICAL[:6])
        healthy_conversation = await seed_conversation(db_session, team=team, creator=owner)
        healthy = await seed_run(
            db_session,
            conversation=healthy_conversation,
            requested_by=owner,
            status=RunStatus.RUNNING,
            worker_id="alive:1",
            heartbeat_at=datetime.now(UTC),
        )
        reap = ReapStaleRuns(sessions)

        assert await reap.execute() == 1

        await db_session.refresh(lost)
        assert (lost.status, lost.attempt, lost.worker_id, lost.heartbeat_at, lost.last_seq) == (
            "queued",
            2,
            None,
            None,
            6,
        )
        await db_session.refresh(healthy)
        assert healthy.status == "running"

        # A second worker picks it up and is lost as well.
        reclaimed = await ClaimRun(sessions).execute(worker_id="dead:2")
        assert reclaimed is not None
        assert reclaimed.id == lost.id
        await db_session.refresh(lost)
        lost.heartbeat_at = stale_at
        await db_session.flush()

        assert await reap.execute() == 1

        await db_session.refresh(lost)
        assert (lost.status, lost.error, lost.last_seq) == ("failed", INTERRUPTED_TEXT, 7)
        assert lost.finished_at is not None
        assert (await _events(db_session, lost))[-1] == (7, "error")
        message = await _assistant_message(db_session, lost)
        assert message is not None
        assert (message.role, message.position, message.parts) == ("assistant", 1, fold_parts(CANONICAL[:6]))
        assert await reap.execute() == 0


class TestOneActiveRunPerConversation:
    async def test_partial_unique_index_rejects_a_second_active_run(
        self, db_session: AsyncSession, conversation: ConversationModel, owner: UserModel, queued: RunModel
    ) -> None:
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await seed_run(db_session, conversation=conversation, requested_by=owner, status=RunStatus.RUNNING)

        # The savepoint rolled back; the transaction is usable and finished runs are not limited.
        done = await seed_run(db_session, conversation=conversation, requested_by=owner, status=RunStatus.SUCCEEDED)
        assert done.id != queued.id
