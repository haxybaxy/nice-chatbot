"""Build the LangChain chat model for a :class:`ModelSpec` — the only place a provider SDK is configured.

Claude goes through ``ChatAnthropic`` (adaptive thinking always on, ``effort`` per run, automatic
prompt-cache breakpoint on every call, strict tools); OpenAI-compatible servers (vLLM, Ollama,
unsloth) go through ``ChatOpenAI`` with ``base_url``. Claude is never routed through
``ChatOpenAI`` — ``parse_model_id`` refuses ``openai:claude-*`` at startup.

:class:`BuiltModel` is what the agent graph consumes: the unbound model, the per-call kwargs the
provider needs, how the system prompt must be shaped, and how to bind tools. ``ChatModelFactory``
is the DI seam (the worker's ``llm`` argument); tests inject
``tests.fakes_llm.FakeChatModelFactory``.
"""

# Library boundary: the provider constructors and `bind_tools` are typed with `Any`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Literal, Protocol
from uuid import UUID

from langchain_anthropic import ChatAnthropic  # noqa: TID251
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI  # noqa: TID251
from pydantic import SecretStr

from app.core.config import OPENAI_DEFAULT_BASE_URL, Effort, llm_settings
from app.core.exceptions import AppError
from app.core.llm.catalog import ModelSpec
from app.core.ui_stream import JsonObject

type SystemFormat = Literal["blocks", "text"]
# LangGraph skips token streaming for models tagged "nostream" (titles, planners, checkers).
NOSTREAM_TAG = "nostream"
_ADAPTIVE_THINKING: dict[str, object] = {"type": "adaptive", "display": "summarized"}
_OPENAI_EFFORTS: dict[Effort, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "xhigh",
}


@dataclass(frozen=True, slots=True)
class BuiltModel:
    """A configured chat model plus everything the caller must pass along on each call."""

    spec: ModelSpec
    model: BaseChatModel
    # Keyword arguments for every `ainvoke` / `astream` (Anthropic: the automatic cache breakpoint).
    invoke_kwargs: Mapping[str, object]
    # "blocks": the system prompt is a list of text blocks (cache_control on the stable one); "text": one string.
    system_format: SystemFormat
    # `bind_tools` options: Anthropic binds strict tools; an OpenAI-compatible server gets
    # `parallel_tool_calls` only when the setting says it understands it. Never a forced `tool_choice`.
    strict_tools: bool | None
    parallel_tool_calls: bool | None

    def runnable(self, tools: Sequence[BaseTool] = ()) -> Runnable[LanguageModelInput, AIMessage]:
        """The model ready to call: ``tools`` bound the way its provider wants, ``invoke_kwargs`` applied."""
        bound: Runnable[LanguageModelInput, AIMessage] = self.model
        if tools:
            bound = self.model.bind_tools(
                list(tools), strict=self.strict_tools, parallel_tool_calls=self.parallel_tool_calls
            )
        if self.invoke_kwargs:
            bound = bound.bind(**self.invoke_kwargs)
        return bound


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Everything ``build_chat_model`` reads from settings, passed explicitly so tests can vary it."""

    anthropic_api_key: str | None
    anthropic_base_url: str | None
    openai_api_key: str | None
    openai_base_url: str
    default_max_tokens: int
    request_timeout_s: float
    max_retries: int
    openai_max_tokens_param: Literal["max_completion_tokens", "max_tokens"]
    openai_parallel_tool_calls: bool

    @classmethod
    def from_settings(cls) -> ProviderConfig:
        anthropic_key = llm_settings.anthropic_api_key
        openai_key = llm_settings.openai_api_key
        return cls(
            anthropic_api_key=anthropic_key.get_secret_value() if anthropic_key else None,
            anthropic_base_url=llm_settings.anthropic_base_url,
            openai_api_key=openai_key.get_secret_value() if openai_key else None,
            openai_base_url=llm_settings.openai_base_url,
            default_max_tokens=llm_settings.llm_max_tokens,
            request_timeout_s=llm_settings.llm_request_timeout_s,
            max_retries=llm_settings.llm_max_retries,
            openai_max_tokens_param=llm_settings.llm_openai_max_tokens_param,
            openai_parallel_tool_calls=llm_settings.llm_openai_parallel_tool_calls,
        )


class ChatModelFactory(Protocol):
    def build(
        self,
        spec: ModelSpec,
        *,
        effort: Effort,
        purpose: str,
        max_tokens: int | None = None,
        output_schema: JsonObject | None = None,
        user_id: UUID | None = None,
        silent: bool = False,
    ) -> BuiltModel:
        """A model for one job. ``purpose`` tags the traces; ``silent`` disables token streaming."""
        ...


def _tags(purpose: str, *, silent: bool) -> list[str]:
    tags = [f"purpose:{purpose}"]
    if silent:
        tags.append(NOSTREAM_TAG)
    return tags


def _build_anthropic(
    spec: ModelSpec,
    config: ProviderConfig,
    *,
    effort: Effort,
    purpose: str,
    max_tokens: int,
    output_schema: JsonObject | None,
    user_id: UUID | None,
    silent: bool,
) -> BuiltModel:
    if config.anthropic_api_key is None:
        raise AppError.service_unavailable("LLM provider not configured", provider="anthropic", model=spec.id)
    output_config: dict[str, object] | None = None
    if output_schema is not None:
        output_config = {"format": {"type": "json_schema", "schema": dict(output_schema)}}
    # Parameter names are the pydantic aliases (what pyright sees on the synthesized `__init__`).
    model = ChatAnthropic(
        model_name=spec.model_id,
        api_key=SecretStr(config.anthropic_api_key),
        base_url=config.anthropic_base_url,
        max_tokens_to_sample=max_tokens,
        stop=None,
        max_retries=config.max_retries,
        timeout=config.request_timeout_s,
        thinking=dict(_ADAPTIVE_THINKING),
        effort=effort,
        output_config=output_config,
        stream_usage=True,
        tags=_tags(purpose, silent=silent),
        metadata={"purpose": purpose},
    )
    if user_id is not None:
        # The Anthropic request-level `metadata` (abuse attribution) is a model kwarg, but the
        # constructor relocates a `metadata` key out of `model_kwargs` onto LangChain's callback
        # metadata; setting the field after construction keeps the two apart.
        model.model_kwargs = {"metadata": {"user_id": str(user_id)}}
    return BuiltModel(
        spec=spec,
        model=model,
        invoke_kwargs={"cache_control": {"type": "ephemeral"}},
        system_format="blocks",
        strict_tools=True,
        parallel_tool_calls=None,
    )


def _build_openai(
    spec: ModelSpec,
    config: ProviderConfig,
    *,
    effort: Effort,
    purpose: str,
    max_tokens: int,
    output_schema: JsonObject | None,
    silent: bool,
) -> BuiltModel:
    # OpenAI itself needs a key; another OpenAI-compatible server is usable as soon as it is named.
    if config.openai_api_key is None and config.openai_base_url == OPENAI_DEFAULT_BASE_URL:
        raise AppError.service_unavailable("LLM provider not configured", provider="openai", model=spec.id)
    # ChatOpenAI always renders `max_tokens` as `max_completion_tokens`; servers that only know
    # the legacy name get it through `extra_body` instead.
    legacy_max_tokens = config.openai_max_tokens_param == "max_tokens"
    model = ChatOpenAI(
        model=spec.model_id,
        api_key=SecretStr(config.openai_api_key or "not-needed"),
        base_url=config.openai_base_url,
        max_retries=config.max_retries,
        timeout=config.request_timeout_s,
        stream_usage=True,
        use_responses_api=False,
        max_completion_tokens=None if legacy_max_tokens else max_tokens,
        extra_body={"max_tokens": max_tokens} if legacy_max_tokens else None,
        reasoning_effort=_OPENAI_EFFORTS[effort] if spec.supports_reasoning else None,
        # Servers that reject the parameter never see it; when enabled it is bound per tool set.
        disabled_params=None if config.openai_parallel_tool_calls else {"parallel_tool_calls": None},
        tags=_tags(purpose, silent=silent),
        metadata={"purpose": purpose},
    )
    invoke_kwargs: dict[str, object] = {}
    if output_schema is not None:
        invoke_kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "output", "schema": dict(output_schema)},
        }
    return BuiltModel(
        spec=spec,
        model=model,
        invoke_kwargs=invoke_kwargs,
        system_format="text",
        strict_tools=None,
        parallel_tool_calls=True if config.openai_parallel_tool_calls else None,
    )


def build_chat_model(
    spec: ModelSpec,
    config: ProviderConfig,
    *,
    effort: Effort,
    purpose: str,
    max_tokens: int | None = None,
    output_schema: JsonObject | None = None,
    user_id: UUID | None = None,
    silent: bool = False,
) -> BuiltModel:
    """Configure the provider model for ``spec``; 503 when the provider has no credentials."""
    tokens = max_tokens if max_tokens is not None else config.default_max_tokens
    if spec.provider == "anthropic":
        return _build_anthropic(
            spec,
            config,
            effort=effort,
            purpose=purpose,
            max_tokens=tokens,
            output_schema=output_schema,
            user_id=user_id,
            silent=silent,
        )
    return _build_openai(
        spec, config, effort=effort, purpose=purpose, max_tokens=tokens, output_schema=output_schema, silent=silent
    )


class DefaultChatModelFactory:
    """:class:`ChatModelFactory` over :func:`build_chat_model` with a fixed :class:`ProviderConfig`."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def build(
        self,
        spec: ModelSpec,
        *,
        effort: Effort,
        purpose: str,
        max_tokens: int | None = None,
        output_schema: JsonObject | None = None,
        user_id: UUID | None = None,
        silent: bool = False,
    ) -> BuiltModel:
        return build_chat_model(
            spec,
            self._config,
            effort=effort,
            purpose=purpose,
            max_tokens=max_tokens,
            output_schema=output_schema,
            user_id=user_id,
            silent=silent,
        )


@cache
def default_chat_model_factory() -> ChatModelFactory:
    return DefaultChatModelFactory(ProviderConfig.from_settings())
