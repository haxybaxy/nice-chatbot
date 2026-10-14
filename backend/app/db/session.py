"""Async engine, session factory and the request-scoped session dependency."""

from collections.abc import AsyncIterator
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


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a session; commit on success, roll back on error.

    Repositories only ``flush()``; this is the single place a request transaction commits.
    ``DbDep`` injects it with ``scope="function"`` so the commit runs *before* the response is
    sent — a commit-time failure (e.g. a unique violation) becomes a proper error response
    instead of being lost after a 2xx.
    """
    async with async_session_maker() as session:
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


DbDep = Annotated[AsyncSession, Depends(get_db, scope="function")]
