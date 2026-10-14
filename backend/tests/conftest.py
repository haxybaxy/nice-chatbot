"""Shared fixtures.

The environment bootstrap at the top must run before anything imports ``app``: the app's
``Settings`` reads the process environment once, and ``app.db.session`` builds its engine at
import time from ``DATABASE_URL``.

Database strategy: the schema is rebuilt from ``Base.metadata`` once per session on the app's
own engine; every test runs inside an outer transaction that is rolled back at the end, with
the session joined in ``create_savepoint`` mode so the app's real commit/rollback code runs
unchanged (a commit only releases a SAVEPOINT). ``tests/guards`` never requests ``engine``, so
it runs without Postgres.

Route coverage: the ``client`` fixture records which endpoint served each request, and
``pytest_sessionfinish`` fails a full, otherwise-green run if any API operation was never
exercised — every route ships with an HTTP test.
"""

import os
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.types import Receive, Scope, Send

ROOT = Path(__file__).resolve().parents[1]


class _TestEnv(BaseSettings):
    """Reads ``.env`` (when present) without importing the app's ``Settings``."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    test_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/acme_test"
    database_url: str | None = None


_env = _TestEnv()
if _env.database_url is not None and _env.database_url == _env.test_database_url:
    pytest.exit(
        "TEST_DATABASE_URL equals DATABASE_URL — the suite drops and rebuilds that database's schema. "
        "Point TEST_DATABASE_URL at a separate database (docker-init creates `acme_test`).",
        returncode=1,
    )

# Process environment outranks .env in pydantic-settings, so these redirects win.
os.environ["DATABASE_URL"] = _env.test_database_url
for _key, _value in {
    "ENVIRONMENT": "test",
    # Pinned so the OpenAPI snapshot (tests/guards) does not depend on a developer's .env.
    "PROJECT_NAME": "Acme API",
    "COGNITO_USER_POOL_ID": "eu-west-1_TESTPOOL",
    "COGNITO_CLIENT_ID": "test-client-id",
    "AWS_REGION": "eu-west-1",
    "FRONTEND_URL": "http://localhost:3000",
    "LOG_FORMAT": "console",
}.items():
    os.environ.setdefault(_key, _value)

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.cognito import get_cognito_client
from app.core.mail import get_mail_client
from app.core.security import get_current_user
from app.db.base import Base
from app.db.registry import register_all_models
from app.db.session import engine as app_engine
from app.db.session import get_db
from app.main import app
from app.users.models import UserModel
from tests.fakes import FakeCognitoClient, FakeMailClient
from tests.routing import iter_api_routes

register_all_models()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-openapi-snapshot",
        action="store_true",
        default=False,
        help="rewrite tests/guards/openapi.snapshot.json from the current app (just openapi-snapshot)",
    )


_exercised_endpoints: set[object] = set()


async def _recording_app(scope: Scope, receive: Receive, send: Send) -> None:
    """The real app, noting which endpoint handled each HTTP request (see pytest_sessionfinish)."""
    try:
        await app(scope, receive, send)
    finally:
        if scope["type"] == "http" and scope.get("endpoint") is not None:
            _exercised_endpoints.add(scope["endpoint"])


def pytest_sessionfinish(session: pytest.Session, exitstatus: int | pytest.ExitCode) -> None:
    """Fail a full, otherwise-green run if any API operation was never requested by a test."""
    config = session.config
    is_full_run = (
        config.args_source is pytest.Config.ArgsSource.TESTPATHS
        and not config.getoption("keyword")
        and not config.getoption("markexpr")
    )
    if exitstatus != 0 or not is_full_run:
        return
    missing = [
        f"{method} {ctx.path}"
        for ctx, route in iter_api_routes(app)
        if route.endpoint not in _exercised_endpoints
        for method in sorted(route.methods or ())
    ]
    if not missing:
        return
    writer = config.get_terminal_writer()
    writer.sep("=", "API operations without an HTTP test", red=True)
    for operation in missing:
        writer.line(f"  {operation}", red=True)
    writer.line("Every route ships with at least one test through the `client` fixture (CLAUDE.md → Testing).")
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """Rebuild the test schema from ``Base.metadata`` once per session.

    No ``drop_all`` on teardown: rebuilding at the *start* is deterministic even after an
    interrupted run, and unlike ``drop_all`` it also clears objects outside the metadata.
    """
    async with app_engine.begin() as conn:
        # A second suite running against this database would otherwise hang on the DROP.
        await conn.execute(text("SET lock_timeout = '10s'"))
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    yield app_engine
    await app_engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is rolled back after the test."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest.fixture
def cognito() -> FakeCognitoClient:
    return FakeCognitoClient()


@pytest.fixture
def mail() -> FakeMailClient:
    return FakeMailClient()


@pytest.fixture
async def client(
    db_session: AsyncSession, cognito: FakeCognitoClient, mail: FakeMailClient
) -> AsyncIterator[AsyncClient]:
    """HTTP client with the database session and the AWS clients (Cognito, mail) swapped for test doubles."""

    async def _get_db() -> AsyncIterator[AsyncSession]:
        # Same contract as app.db.session.get_db (commit on success, roll back on error), on the
        # test's transaction. Rows the test seeded before the request are released first and the
        # request runs in its own SAVEPOINT, so a failing request rolls back only its own work —
        # like pre-existing committed data in production — and objects the test still holds are
        # not expired (a session-level rollback would expire them all).
        await db_session.commit()
        request_tx = await db_session.begin_nested()
        try:
            yield db_session
        except Exception:
            await request_tx.rollback()
            raise
        else:
            await request_tx.commit()
            await db_session.commit()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_cognito_client] = lambda: cognito
    app.dependency_overrides[get_mail_client] = lambda: mail
    async with AsyncClient(transport=ASGITransport(app=_recording_app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.fixture
def authenticate_as() -> Iterator[Callable[[UserModel], None]]:
    """Bypass JWT verification: ``authenticate_as(user)`` makes ``user`` the current user."""

    def _set(user: UserModel) -> None:
        async def _current_user() -> UserModel:
            return user

        app.dependency_overrides[get_current_user] = _current_user

    yield _set
    app.dependency_overrides.pop(get_current_user, None)
