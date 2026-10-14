"""Async engine, session factory, the request-scoped session dependency and ``session_scope``.

Two ways to get a session, both committing in exactly this module:

* ``DbDep`` — one session per request; ``get_db`` commits before the response is sent.
* ``session_scope()`` — one short unit of work outside a request (a worker step, an SSE poll).
  Long-running code never holds a transaction across an ``await`` on the network: it opens a
  scope per database step. ``SessionScopeDep`` injects the factory into use cases that outlive a
  request (``__init__(self, sessions: SessionScope)``).
"""

from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.config import db_settings

# Backstop for a transaction abandoned across an await (e.g. a hung upstream call) so it can't
# hold locks or a snapshot forever. Statement timeout is a setting.
_IDLE_IN_TRANSACTION_TIMEOUT_MS = 120_000

engine = create_async_engine(
    db_settings.database_url,
    pool_size=db_settings.db_pool_size,
    max_overflow=db_settings.db_max_overflow,
    pool_timeout=db_settings.db_pool_timeout_s,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "options": (
            f"-c statement_timeout={db_settings.db_statement_timeout_ms}"
            f" -c idle_in_transaction_session_timeout={_IDLE_IN_TRANSACTION_TIMEOUT_MS}"
        )
    },
)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _commit_or_rollback(session: AsyncSession) -> AsyncGenerator[AsyncSession]:
    """Commit when the block succeeds, roll back when it raises — the one commit site."""
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    else:
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a session; commit on success, roll back on error.

    Repositories only ``flush()``; this is the single place a request transaction commits.
    ``DbDep`` injects it with ``scope="function"`` so the commit runs *before* the response is
    sent — a commit-time failure (e.g. a unique violation) becomes a proper error response
    instead of being lost after a 2xx.
    """
    async with async_session_maker() as session, _commit_or_rollback(session):
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession]:
    """One short unit of work outside a request: commit on success, roll back on error."""
    async with async_session_maker() as session, _commit_or_rollback(session):
        yield session


type SessionScope = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def get_session_scope() -> SessionScope:
    """The scope factory for use cases that span transactions; tests override it."""
    return session_scope


DbDep = Annotated[AsyncSession, Depends(get_db, scope="function")]
SessionScopeDep = Annotated[SessionScope, Depends(get_session_scope)]
