"""LangGraph checkpointing for crash-resume, in its own Postgres schema.

``PostgresCheckpointer`` owns a dedicated psycopg pool (autocommit, ``prepare_threshold=0``,
``dict_row`` — what ``AsyncPostgresSaver`` requires) whose ``search_path`` is the configured
schema, so LangGraph's unqualified table names land there and Alembic / the migration tests only
ever see ``public``. The worker calls ``open()`` inside its event loop at startup (``CREATE SCHEMA
IF NOT EXISTS`` + ``setup()``), passes ``saver`` to ``build_agent_graph`` with
``configurable.thread_id = run_id``, deletes the thread once the run is terminal, and ``close()``s
on shutdown. ``NullCheckpointer`` (``AGENT_CHECKPOINTER=none``) keeps everything in memory.

Only this module imports ``langgraph.checkpoint.postgres`` (ruff ``TID251``). Deployment note:
set ``LANGGRAPH_STRICT_MSGPACK=true`` so checkpoints never fall back to pickle.
"""

from __future__ import annotations

import re
from functools import cache
from typing import Annotated, Protocol, cast

from fastapi import Depends
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: TID251
from psycopg import AsyncConnection, sql
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import agent_settings
from app.core.exceptions import AppError
from app.core.logging_config import get_logger
from app.db.config import db_settings

logger = get_logger(__name__)

_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class Checkpointer(Protocol):
    @property
    def saver(self) -> BaseCheckpointSaver[str] | None:
        """What ``build_agent_graph`` compiles with; ``None`` means no persistence."""
        ...

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def delete_thread(self, thread_id: str) -> None: ...


class NullCheckpointer:
    """No persistence: a run that loses its worker starts over (tests, ``AGENT_CHECKPOINTER=none``)."""

    @property
    def saver(self) -> BaseCheckpointSaver[str] | None:
        return None

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def delete_thread(self, thread_id: str) -> None:
        del thread_id


def conninfo_for(database_url: str) -> str:
    """psycopg conninfo from the SQLAlchemy URL (``postgresql+psycopg://`` → ``postgresql://``)."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


class PostgresCheckpointer:
    def __init__(self, *, conninfo: str, schema: str, pool_size: int = 4) -> None:
        if not _SCHEMA_NAME.match(schema):
            raise AppError.internal("AGENT_CHECKPOINT_SCHEMA must be a lower-case identifier", schema=schema)
        self._conninfo = conninfo
        self._schema = schema
        self._pool_size = pool_size
        self._pool: AsyncConnectionPool[AsyncConnection[DictRow]] | None = None
        self._saver: AsyncPostgresSaver | None = None

    @property
    def saver(self) -> BaseCheckpointSaver[str] | None:
        return self._saver

    async def open(self) -> None:
        if self._saver is not None:
            return
        # `row_factory=dict_row` makes every connection an `AsyncConnection[DictRow]`; the pool's
        # type parameter cannot see into `kwargs`, hence the cast.
        pool = cast(
            "AsyncConnectionPool[AsyncConnection[DictRow]]",
            AsyncConnectionPool(
                self._conninfo,
                open=False,
                min_size=1,
                max_size=self._pool_size,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                    "options": f"-c search_path={self._schema}",
                },
            ),
        )
        await pool.open(wait=True)
        async with pool.connection() as conn:
            await conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self._schema)))
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        self._pool = pool
        self._saver = saver
        logger.info("checkpointer ready", schema=self._schema)

    async def close(self) -> None:
        self._saver = None
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def delete_thread(self, thread_id: str) -> None:
        if self._saver is not None:
            await self._saver.adelete_thread(thread_id)


def build_checkpointer() -> Checkpointer:
    """The checkpointer ``agent_settings`` asks for; ``open()`` it before the first run."""
    if agent_settings.agent_checkpointer == "none":
        return NullCheckpointer()
    return PostgresCheckpointer(
        conninfo=conninfo_for(db_settings.database_url), schema=agent_settings.agent_checkpoint_schema
    )


@cache
def default_checkpointer() -> Checkpointer:
    return build_checkpointer()


async def get_checkpointer() -> Checkpointer:
    return default_checkpointer()


CheckpointerDep = Annotated[Checkpointer, Depends(get_checkpointer)]
