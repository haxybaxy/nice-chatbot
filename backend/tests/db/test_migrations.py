"""Guards on the migration chain: one head, and `upgrade head` produces exactly the models' schema."""

import asyncio
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text  # noqa: TID251
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import Base
from app.db.config import db_settings

ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    # `%(here)s` in alembic.ini makes this CWD-independent.
    return Config(str(ROOT / "alembic.ini"))


def test_single_migration_head() -> None:
    """Two heads make `alembic upgrade head` ambiguous and abort a deploy; fix with `alembic merge heads`."""
    heads = ScriptDirectory.from_config(_alembic_config()).get_heads()

    assert len(heads) == 1, f"Expected exactly one Alembic head, found {sorted(heads)}"


def _upgrade_compare_downgrade() -> list[object]:
    """Runs in a worker thread: env.py calls asyncio.run(), which cannot nest inside the test loop.

    psycopg 3 serves the sync API under the same `postgresql+psycopg` URL.
    """
    sync_engine = create_engine(db_settings.database_url)
    try:
        with sync_engine.begin() as conn:
            conn.execute(text("SET lock_timeout = '10s'"))
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))

        config = _alembic_config()
        command.upgrade(config, "head")
        with sync_engine.connect() as conn:
            diff = list(compare_metadata(MigrationContext.configure(conn), Base.metadata))
        command.downgrade(config, "base")

        # Restore the metadata-built schema the rest of the suite runs against.
        with sync_engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            Base.metadata.create_all(conn)
        return diff
    finally:
        sync_engine.dispose()


async def test_upgrade_head_matches_the_models(engine: AsyncEngine) -> None:
    """Deliberately takes no `db_session`: DROP SCHEMA needs every other connection idle."""
    diff = await asyncio.to_thread(_upgrade_compare_downgrade)
    # Pooled async connections predate the schema rebuild; start fresh ones.
    await engine.dispose()

    assert diff == [], f"Migrations and models have drifted:\n{diff}"
