"""The real Postgres pieces that the rolled-back test transaction cannot exercise.

These tests COMMIT rows (``session_scope()`` on the test database) and clean up with
``TRUNCATE … CASCADE`` because ``NOTIFY`` only fires on commit and ``SKIP LOCKED`` only shows
between two transactions. They request ``engine`` so the schema exists.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chat.models import RunStatus
from app.chat.repository import RunRepository
from app.chat.use_cases.claim_run import ClaimRun
from app.db.listen import PgListener, listener_conninfo
from app.db.session import session_scope
from tests.seeds import seed_conversation, seed_organization, seed_run, seed_team, seed_user


@pytest.fixture
async def listener(engine: AsyncEngine) -> AsyncIterator[PgListener]:
    del engine  # only to guarantee the database is up
    listener = PgListener(listener_conninfo())
    await listener.start()
    yield listener
    await listener.stop()


@pytest.fixture
async def committed_rows(engine: AsyncEngine) -> AsyncIterator[None]:
    """Real committed rows for the lock tests; truncated afterwards (cascades through
    organization, team, conversation, run, run_event)."""
    del engine
    try:
        yield
    finally:
        async with session_scope() as session:
            await session.execute(text('TRUNCATE "user" CASCADE'))


async def _notify(channel: str, payload: str) -> None:
    async with session_scope() as session:
        await session.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": channel, "payload": payload})


class TestPgListener:
    async def test_committed_notify_wakes_the_keyed_and_wildcard_waiters(self, listener: PgListener) -> None:
        assert listener.listening
        async with (
            listener.subscribe("run_events", "run-1") as keyed,
            listener.subscribe("run_events") as any_run,
            listener.subscribe("run_events", "run-2") as other,
            listener.subscribe("run_queue", "run-1") as other_channel,
        ):
            await _notify("run_events", "run-1:7")

            await asyncio.wait_for(keyed.wait(), 1.0)
            await asyncio.wait_for(any_run.wait(), 1.0)
            assert not other.is_set()
            assert not other_channel.is_set()

    async def test_wait_returns_false_on_timeout_and_true_on_notify(self, listener: PgListener) -> None:
        assert await listener.wait("run_queue", timeout_s=0.1) is False

        async def notify_soon() -> None:
            await asyncio.sleep(0.05)
            await _notify("run_queue", "run-9")

        notifier = asyncio.create_task(notify_soon())
        assert await listener.wait("run_queue", timeout_s=2.0) is True
        await notifier

    async def test_stop_closes_the_connection(self, engine: AsyncEngine) -> None:
        del engine
        listener = PgListener(listener_conninfo())
        await listener.start()
        assert listener.listening
        await listener.stop()
        assert not listener.listening


class TestSkipLockedClaims:
    @pytest.mark.usefixtures("committed_rows")
    async def test_two_workers_never_claim_the_same_run(self) -> None:
        async with session_scope() as setup:
            owner = await seed_user(setup, email="worker-race@example.com")
            organization = await seed_organization(setup, name="Race", owner=owner)
            team = await seed_team(setup, organization=organization, name="Race", creator=owner)
            first = await seed_run(
                setup, conversation=await seed_conversation(setup, team=team, creator=owner), requested_by=owner
            )
            second = await seed_run(
                setup, conversation=await seed_conversation(setup, team=team, creator=owner), requested_by=owner
            )
        expected = {first.id, second.id}

        # Worker A holds its claimed row locked (its transaction is still open) while worker B
        # claims: SKIP LOCKED makes B take the other run instead of waiting.
        async with session_scope() as a, session_scope() as b:
            run_a = await RunRepository(a).lock_next_queued()
            run_b = await RunRepository(b).lock_next_queued()
            assert run_a is not None
            assert run_b is not None
            assert {run_a.id, run_b.id} == expected
            for run, worker in ((run_a, "a"), (run_b, "b")):
                run.status = RunStatus.RUNNING.value
                run.worker_id = worker
            await a.flush()
            await b.flush()

        assert await ClaimRun(session_scope).execute(worker_id="c") is None
