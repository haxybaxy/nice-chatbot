"""Application settings, one object per concern.

Every environment variable the app reads is a field on one of the ``BaseSettings`` classes —
never read ``os.environ`` anywhere else under ``app/`` (ruff ``TID251`` bans it). Field names map
to env vars case-insensitively (``log_level`` ← ``LOG_LEVEL``); the process environment outranks
``.env``. Each consumer imports only the object it needs, so Alembic (``db_settings``) starts
without the Cognito variables and the AWS adapters never see the database URL.

- :class:`Settings` → ``settings``: deploy tier, app identity, frontend URL, logging, CORS
- :class:`AwsSettings` → ``aws_settings``: static AWS credentials shared by every boto3 adapter
- :class:`CognitoSettings` → ``cognito_settings``: the user pool and its region
- :class:`MailSettings` → ``mail_settings``: the SES sender, fixed in code — a plain dataclass,
  deliberately not environment-configurable, so it has no ``.env`` lines
- :class:`DatabaseSettings` → ``db_settings`` (``app/db/config.py``): URL and pool sizing

``tests/guards/test_settings.py`` keeps ``.env.example`` in sync with the ``BaseSettings`` fields.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: TID251

# backend/.env — anchored to this file so it is found from any working directory (pre-commit
# runs from the repo root).
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# Deploy tiers, keyed on ENVIRONMENT. Anything else refuses to start: a typo must not silently
# pick a tier.
#   local, test        → console logs, /docs on, error details in responses
#   develop, staging   → JSON logs, /docs on, error details in responses
#   prod, production   → JSON logs, /docs off, error details masked
Environment = Literal["local", "test", "develop", "staging", "prod", "production"]
_LOCAL_ENVIRONMENTS: frozenset[str] = frozenset({"local", "test"})
_DEBUG_ENVIRONMENTS: frozenset[str] = frozenset({"local", "test", "develop", "staging"})


def settings_config() -> SettingsConfigDict:
    """``model_config`` shared by every settings class."""
    return SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = settings_config()

    environment: Environment = "local"
    project_name: str = "Acme API"
    version: str = "0.1.0"
    # Where the SPA is served; links in outgoing mail (password reset) point at it.
    frontend_url: str = "http://localhost:3000"

    log_level: str = "info"
    log_format: Literal["auto", "json", "console"] = "auto"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @field_validator("frontend_url", mode="after")
    @classmethod
    def _no_trailing_slash(cls, value: str) -> str:
        # Paths are appended verbatim, so "https://app.example/" would produce a double slash.
        return value.rstrip("/")

    @field_validator("cors_origins", mode="after")
    @classmethod
    def _no_wildcard_origin(cls, value: list[str]) -> list[str]:
        # The app sends allow_credentials=True; browsers reject "*" with credentials, and an
        # explicit allow-list is the whole point of the setting.
        if "*" in value:
            raise ValueError("CORS_ORIGINS must list explicit origins; '*' is not allowed")
        return value

    @property
    def is_local(self) -> bool:
        """Developer machine or test run: colored console logs."""
        return self.environment in _LOCAL_ENVIRONMENTS

    @property
    def expose_debug_details(self) -> bool:
        """Serve /docs and include error details in responses. Off for prod."""
        return self.environment in _DEBUG_ENVIRONMENTS


class AwsSettings(BaseSettings):
    """Static credentials for boto3, shared by the Cognito and SES adapters.

    Optional: when unset, boto3 resolves credentials from its default chain (process env vars,
    shared config / profile, IAM role). They are settings rather than process-only so that a
    ``.env`` file configures both adapters the same way.
    """

    model_config: ClassVar[SettingsConfigDict] = settings_config()

    aws_access_key_id: str | None = None
    aws_secret_access_key: SecretStr | None = None


class CognitoSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = settings_config()

    # The user pool lives in aws_region; credentials come from AwsSettings.
    aws_region: str = "us-west-1"

    cognito_user_pool_id: str
    cognito_client_id: str
    # Only for a confidential app client; SECRET_HASH is computed when set.
    cognito_client_secret: SecretStr | None = None

    @property
    def issuer(self) -> str:
        """Expected ``iss`` claim for tokens from this pool (also the JWKS host)."""
        return f"https://cognito-idp.{self.aws_region}.amazonaws.com/{self.cognito_user_pool_id}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"


@dataclass(frozen=True, slots=True)
class MailSettings:
    """The SES sender, fixed in code by design.

    Not a ``BaseSettings``: nothing here can be overridden from the environment, and the
    ``.env.example`` guard does not see it. ``region`` is where the sending identity is verified,
    independent of the user pool's region.
    """

    sender_address: str = "noreply@example.com"
    sender_name: str = "Acme"
    region: str = "us-west-1"


settings = Settings()
aws_settings = AwsSettings()
# Required fields (no defaults) come from the environment, which pyright can't see.
cognito_settings = CognitoSettings()  # pyright: ignore[reportCallIssue]
mail_settings = MailSettings()
