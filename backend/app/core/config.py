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
- :class:`ChatSettings` / :class:`WorkerSettings`: run limits and the worker loop
- :class:`AttachmentSettings` → ``attachment_settings``: upload size, per-message count, text caps, orphan TTL
- :class:`LlmSettings` / :class:`AgentSettings`: model providers, allowlist, agent budgets
- :class:`SearchSettings` / :class:`SandboxSettings` / :class:`ResearchSettings`: tools and deep research
- :class:`LangfuseSettings` → ``langfuse_settings``: tracing (no-op when unset)

``tests/guards/test_settings.py`` keeps ``.env.example`` in sync with the ``BaseSettings`` fields.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
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
    project_name: str = "Nice Chatbot API"
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
    sender_name: str = "Nice Chatbot"
    region: str = "us-west-1"


# ── Chat, agent runtime, providers and observability ──────────────────────────
# Every class below has defaults, so the API and the worker boot with none of these set: a
# missing provider key hides that provider's models, a missing search key drops the web tools, a
# missing Langfuse key makes tracing a no-op. Only *inconsistent* configuration refuses to start.


def _blank_to_none(value: object) -> object:
    """Treat an empty environment value (``KEY=``) as unset — the only way to override a .env entry."""
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


Effort = Literal["low", "medium", "high", "xhigh", "max"]
LlmProvider = Literal["anthropic", "openai"]
_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai"})
# Model ids are never date-suffixed snapshots (claude-opus-5-5, not claude-opus-5-5-20260401).
_DATE_SUFFIX = re.compile(r"-\d{8}$")


def parse_model_id(value: str) -> tuple[LlmProvider, str]:
    """``"anthropic:claude-opus-5-5"`` → ``("anthropic", "claude-opus-5-5")``, or ``ValueError``.

    Claude is reached only through the Anthropic provider — ``openai:claude-*`` would route it
    through an OpenAI-compatible shim and is rejected here.
    """
    provider, separator, model_id = value.partition(":")
    if not separator or not model_id or provider not in _PROVIDERS:
        raise ValueError(f"model id {value!r} must look like '<anthropic|openai>:<model-id>'")
    if _DATE_SUFFIX.search(model_id):
        raise ValueError(f"model id {value!r} must not carry a date suffix; use the alias (e.g. claude-opus-5-5)")
    if provider == "openai" and model_id.startswith("claude"):
        raise ValueError(f"{value!r}: Claude models go through the anthropic provider, never an OpenAI-compatible one")
    return ("anthropic" if provider == "anthropic" else "openai", model_id)


class ChatSettings(BaseSettings):
    """Per-run limits for the chat domain (the worker's agent loop and the SSE endpoint)."""

    model_config: ClassVar[SettingsConfigDict] = settings_config()

    # Wall clock for one assistant turn (deep research included) before the run is failed.
    chat_run_timeout_s: int = 900
    # Oldest messages beyond this count are not sent to the model.
    chat_history_max_messages: int = 60
    # SSE keep-alive comment interval while a run is idle.
    chat_sse_ping_interval_s: int = 15
    # How long the finishing run waits for the conversation title before emitting `finish`.
    chat_title_timeout_s: int = 10


class WorkerSettings(BaseSettings):
    """The run worker (``python -m app.worker``): claim loop, heartbeats, reaper, event batching."""

    model_config: ClassVar[SettingsConfigDict] = settings_config()

    worker_concurrency: int = 4
    worker_poll_interval_s: float = 5.0
    worker_heartbeat_interval_s: float = 2.0
    # A running run whose heartbeat is older than this is considered lost (re-queued once, then failed).
    worker_stale_after_s: int = 30
    worker_reaper_interval_s: int = 15
    # Text deltas are coalesced for this long before they are written to run_event and notified.
    worker_event_flush_ms: int = 75
    worker_shutdown_grace_s: int = 20


class AttachmentSettings(BaseSettings):
    """File attachments on chat messages: upload limits, what is extracted and kept, and how much of
    it a model sees in one turn."""

    model_config: ClassVar[SettingsConfigDict] = settings_config()

    # Largest accepted upload; the request is read in chunks and refused past this point.
    attachment_max_bytes: int = 10_485_760
    attachment_max_per_message: int = 5
    # Extracted text kept per attachment (`text_chars` still records the full count).
    attachment_max_extracted_chars: int = 200_000
    # Attachment text injected into one model turn, across every attachment in the history window.
    attachment_model_text_chars: int = 60_000
    # Uploads never attached to a message are swept by the worker's reaper after this long.
    attachment_orphan_ttl_hours: int = 24


class LlmSettings(BaseSettings):
    """Model providers and the model allowlist.

    ``anthropic:*`` models need ``ANTHROPIC_API_KEY``; ``openai:*`` models need ``OPENAI_BASE_URL``
    (an OpenAI-compatible server such as vLLM or Ollama — the key is optional for those).
    """

    model_config: ClassVar[SettingsConfigDict] = settings_config()

    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str | None = None
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None

    # JSON list of "<provider>:<model-id>" offered in the model picker.
    llm_models: list[str] = Field(
        default_factory=lambda: [
            "anthropic:claude-opus-5-5",
            "anthropic:claude-sonnet-5-5",
            "anthropic:claude-haiku-5-5",
        ]
    )
    llm_default_model: str = "anthropic:claude-opus-5-5"
    # Cheap model for conversation titles and the research citation check.
    llm_title_model: str = "anthropic:claude-haiku-5-5"
    llm_default_effort: Effort = "medium"
    llm_max_tokens: int = 64_000
    llm_request_timeout_s: float = 600.0
    llm_max_retries: int = 2

    # Capabilities of the OpenAI-compatible server (one server, one setting each).
    llm_openai_supports_tools: bool = True
    llm_openai_supports_reasoning: bool = False
    # Whether it accepts image content blocks (Claude always does); without it, attached images
    # reach the model as a text placeholder.
    llm_openai_supports_vision: bool = False
    llm_openai_parallel_tool_calls: bool = False
    # vLLM/Ollama accept `max_tokens`; api.openai.com wants `max_completion_tokens`.
    llm_openai_max_tokens_param: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"

    @field_validator("anthropic_api_key", "anthropic_base_url", "openai_api_key", "openai_base_url", mode="before")
    @classmethod
    def _optional(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("llm_models", mode="after")
    @classmethod
    def _valid_model_ids(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("LLM_MODELS must list at least one model")
        for model_id in value:
            parse_model_id(model_id)
        if len(set(value)) != len(value):
            raise ValueError("LLM_MODELS lists a model twice")
        return value

    @model_validator(mode="after")
    def _defaults_are_listed(self) -> Self:
        for name, model_id in (
            ("LLM_DEFAULT_MODEL", self.llm_default_model),
            ("LLM_TITLE_MODEL", self.llm_title_model),
        ):
            parse_model_id(model_id)
            if model_id not in self.llm_models:
                raise ValueError(f"{name}={model_id!r} is not in LLM_MODELS")
        return self

    @property
    def anthropic_configured(self) -> bool:
        return self.anthropic_api_key is not None

    @property
    def openai_configured(self) -> bool:
        return self.openai_base_url is not None


class AgentSettings(BaseSettings):
    """The LangGraph agent loop: checkpointing and step budgets."""

    model_config: ClassVar[SettingsConfigDict] = settings_config()

    # postgres: graph state per run in its own schema (crash-resume); none: in-memory (tests).
    agent_checkpointer: Literal["postgres", "none"] = "postgres"
    agent_checkpoint_schema: str = "langgraph"
    agent_max_model_calls: int = 12
    agent_max_tool_calls: int = 24
    agent_max_tool_calls_per_step: int = 8


class SearchSettings(BaseSettings):
    """Web search / page extraction provider (Tavily). Unset → the web tools are not offered."""

    model_config: ClassVar[SettingsConfigDict] = settings_config()

    tavily_api_key: SecretStr | None = None
    search_max_concurrency: int = 8
    search_timeout_s: float = 30.0

    @field_validator("tavily_api_key", mode="before")
    @classmethod
    def _optional(cls, value: object) -> object:
        return _blank_to_none(value)

    @property
    def configured(self) -> bool:
        return self.tavily_api_key is not None


class SandboxSettings(BaseSettings):
    """Code execution sandbox for the `run_code` tool.

    ``docker`` runs each execution in a throwaway container (needs the Docker socket — local
    development only); ``disabled`` hides the tool.
    """

    model_config: ClassVar[SettingsConfigDict] = settings_config()

    sandbox_backend: Literal["docker", "disabled"] = "disabled"
    sandbox_image: str = "python:3.13-slim"
    sandbox_timeout_s: int = 30
    sandbox_max_timeout_s: int = 120
    sandbox_memory: str = "512m"
    sandbox_cpus: str = "1"
    sandbox_pids_limit: int = 128
    sandbox_max_output_bytes: int = 65_536


class ResearchSettings(BaseSettings):
    """Deep-research mode budgets (the orchestrator/subagent graph)."""

    model_config: ClassVar[SettingsConfigDict] = settings_config()

    research_max_subagents: int = 5
    research_max_parallel: int = 3
    research_max_tool_calls_per_subagent: int = 12
    research_max_output_tokens_per_subagent: int = 16_000
    research_total_token_budget: int = 400_000
    research_wall_clock_s: int = 600
    research_citation_check: bool = True


class LangfuseSettings(BaseSettings):
    """Langfuse tracing. Both keys set (and enabled) → traces; otherwise tracing is a no-op."""

    model_config: ClassVar[SettingsConfigDict] = settings_config()

    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_enabled: bool = True

    @field_validator("langfuse_public_key", "langfuse_secret_key", mode="before")
    @classmethod
    def _optional(cls, value: object) -> object:
        return _blank_to_none(value)

    @property
    def configured(self) -> bool:
        return self.langfuse_enabled and self.langfuse_public_key is not None and self.langfuse_secret_key is not None


settings = Settings()
aws_settings = AwsSettings()
# Required fields (no defaults) come from the environment, which pyright can't see.
cognito_settings = CognitoSettings()  # pyright: ignore[reportCallIssue]
mail_settings = MailSettings()
chat_settings = ChatSettings()
worker_settings = WorkerSettings()
attachment_settings = AttachmentSettings()
llm_settings = LlmSettings()
agent_settings = AgentSettings()
search_settings = SearchSettings()
sandbox_settings = SandboxSettings()
research_settings = ResearchSettings()
langfuse_settings = LangfuseSettings()
