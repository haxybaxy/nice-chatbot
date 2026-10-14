"""Fixtures for the worker-side chat tests.

``RunAssistantTurn`` writes from several tasks at once (the turn itself, its lease watcher, the
sink's timer flushes). In production each ``session_scope()`` is its own session; in a test they
all share the one rolled-back ``db_session``, whose SAVEPOINTs must not interleave — so
``test_scope`` serializes the scopes with a lock. Tests that touch rows while a turn is running
go through the same scope.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionScope


@pytest.fixture
def test_scope(db_session: AsyncSession) -> SessionScope:
    lock = asyncio.Lock()

    @asynccontextmanager
    async def _scope() -> AsyncGenerator[AsyncSession]:
        async with lock:
            nested = await db_session.begin_nested()
            try:
                yield db_session
            except Exception:
                await nested.rollback()
                raise
            else:
                await nested.commit()

    return _scope
