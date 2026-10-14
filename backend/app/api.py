"""Router composition root + health probes. Nothing under ``app/`` imports this module."""

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.auth.router import router as auth_router
from app.core.config import settings
from app.core.openapi import error_responses
from app.core.schemas import BaseSchemaOut
from app.db.session import async_session_maker
from app.organizations.router import router as organizations_router
from app.users.router import router as users_router

api_router = APIRouter()
# Any domain route can hit an unhandled error (500) or an unavailable dependency (503: database,
# Cognito). The health probes are exempt: liveness is always 200, readiness documents its own 503.
for domain_router in (auth_router, users_router, organizations_router):
    api_router.include_router(domain_router, responses=error_responses(500, 503))


class HealthOut(BaseSchemaOut):
    status: str
    service: str
    version: str


class ReadinessOut(BaseSchemaOut):
    status: str
    checks: dict[str, str]


@api_router.get("/health", tags=["health"], summary="Liveness probe")
async def health() -> HealthOut:
    """Always 200 while the process is up."""
    return HealthOut(status="ok", service=settings.project_name, version=settings.version)


@api_router.get(
    "/health/ready",
    responses={503: {"model": ReadinessOut, "description": "A dependency is unavailable"}},
    tags=["health"],
    summary="Readiness probe",
)
async def readiness(response: Response) -> ReadinessOut:
    """200 when the database answers, 503 otherwise."""
    checks: dict[str, str] = {}
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as error:  # noqa: BLE001
        checks["database"] = f"error: {type(error).__name__}"
    ready = all(value == "ok" for value in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessOut(status="ready" if ready else "not_ready", checks=checks)
