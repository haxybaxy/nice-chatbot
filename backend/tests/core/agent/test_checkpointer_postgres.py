"""``PostgresCheckpointer`` against the test database: own schema, setup, a checkpointed run, cleanup."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.agent.checkpointer import NullCheckpointer, PostgresCheckpointer, build_checkpointer, conninfo_for
from app.core.agent.graph import build_agent_graph, run_config
from app.core.agent.state import AgentLimits
from app.core.exceptions import AppError
from app.core.tools.registry import RunTools
from app.db.config import db_settings
from tests.fakes_llm import make_run_context, scripted_turn
from tests.graph_harness import collect, prompt, scripted_model

SCHEMA = "langgraph_test"


async def test_checkpoints_land_in_their_own_schema_and_threads_can_be_deleted(engine: AsyncEngine) -> None:
    checkpointer = PostgresCheckpointer(conninfo=conninfo_for(db_settings.database_url), schema=SCHEMA)
    assert checkpointer.saver is None
    await checkpointer.open()
    try:
        assert checkpointer.saver is not None
        ctx = make_run_context()
        _, built = scripted_model([scripted_turn("hello")])
        graph = build_agent_graph(built, RunTools(), AgentLimits(), checkpointer=checkpointer.saver, name="chat")
        result = await collect(graph, ctx, prompt())
        assert result.finished.stop.reason == "end"

        config = run_config(thread_id=str(ctx.run_id))
        assert (await graph.aget_state(config)).values["model_calls"] == 1
        async with engine.connect() as conn:
            tables = await conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"),
                {"schema": SCHEMA},
            )
            names = {row[0] for row in tables}
            public = await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE 'checkpoint%'"
                )
            )
        assert "checkpoints" in names
        assert public.fetchall() == []

        await checkpointer.delete_thread(str(ctx.run_id))
        assert (await graph.aget_state(config)).values == {}
    finally:
        await checkpointer.close()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
    assert checkpointer.saver is None


def test_schema_name_is_validated() -> None:
    with pytest.raises(AppError):
        PostgresCheckpointer(conninfo="postgresql://x", schema='bad";DROP SCHEMA public')


async def test_null_checkpointer_and_settings_factory() -> None:
    null = NullCheckpointer()
    await null.open()
    await null.delete_thread("t")
    await null.close()
    assert null.saver is None
    # The test environment pins AGENT_CHECKPOINTER=none.
    assert isinstance(build_checkpointer(), NullCheckpointer)
    assert conninfo_for("postgresql+psycopg://u:p@h/db") == "postgresql://u:p@h/db"
