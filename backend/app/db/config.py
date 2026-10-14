"""Database settings — all that the engine and Alembic need (no Cognito variables)."""

from typing import ClassVar

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: TID251

from app.core.config import settings_config


class DatabaseSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = settings_config()

    # postgresql+psycopg://user:password@host:port/database
    database_url: str
    # Connection pool (per process).
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout_s: int = 30
    # Server-side statement timeout so a runaway query errors out instead of pinning a pool
    # connection forever.
    db_statement_timeout_ms: int = 30_000

    @field_validator("database_url", mode="after")
    @classmethod
    def _ensure_psycopg_driver(cls, value: str) -> str:
        """Normalize a bare ``postgresql://`` URL to the async psycopg driver."""
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value


# Required fields (no defaults) come from the environment, which pyright can't see.
db_settings = DatabaseSettings()  # pyright: ignore[reportCallIssue]
