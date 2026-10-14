"""Application factory (composition root). Run with ``uvicorn app.main:app``."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import api_router
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.core.logging_config import configure_logging, get_logger
from app.core.middleware import RequestLoggingMiddleware
from app.db.session import async_session_maker, engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    # One ping so an operator sees a single clear warning; DB-backed routes answer 503 until
    # the database recovers, and /api/health keeps answering 200.
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
    except Exception as error:  # noqa: BLE001
        logger.warning("database unreachable at startup", error_type=type(error).__name__)
    logger.info("application started", environment=settings.environment)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(
        title=settings.project_name,
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if settings.expose_debug_details else None,
        redoc_url="/redoc" if settings.expose_debug_details else None,
        openapi_url="/openapi.json" if settings.expose_debug_details else None,
        swagger_ui_parameters={"persistAuthorization": True},
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )
    # Added last so it is outermost: every request gets a correlation id before anything else.
    application.add_middleware(RequestLoggingMiddleware)
    application.include_router(api_router, prefix="/api")
    register_exception_handlers(application)
    return application


app = create_app()
