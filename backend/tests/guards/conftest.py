"""Fixtures for the DB-free guards: the app's effective route table and its OpenAPI document.

Nothing in this package touches Postgres or Cognito: importing ``app.main`` builds the engine
without connecting, and ``app.openapi()`` is computed from the route table. ``just guards`` runs
this package alone (also from pre-commit); the full ``just test`` includes it.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi.routing import APIRoute, RouteContext
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.routing import iter_api_routes


@pytest.fixture(scope="session")
def routes() -> list[tuple[RouteContext, APIRoute]]:
    return list(iter_api_routes(app))


@pytest.fixture(scope="session")
def spec() -> dict[str, object]:
    return app.openapi()


@pytest.fixture
async def http() -> AsyncIterator[AsyncClient]:
    """Bare client over the real app (no overrides), for routes that need neither DB nor Cognito."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
