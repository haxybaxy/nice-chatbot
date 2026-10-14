"""The model allowlist as the API and the worker see it.

``LLM_MODELS`` (settings) lists ``"<provider>:<model-id>"`` ids; the catalog decorates each with
display name, tier, capability flags and list prices, hides providers whose credentials are not
configured, and resolves the cheaper sibling used for research subagents. ``ModelOut`` in the chat
domain is built from :class:`ModelSpec` by attribute.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Literal

from app.core.config import LlmProvider, llm_settings, parse_model_id
from app.core.exceptions import AppError

type Tier = Literal["frontier", "balanced", "fast"]
_TIER_ORDER: tuple[Tier, ...] = ("frontier", "balanced", "fast")


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str  # "anthropic:claude-opus-5-5" — what the frontend sends back
    provider: LlmProvider
    model_id: str
    display_name: str
    tier: Tier
    supports_tools: bool
    supports_reasoning: bool
    # Accepts image content blocks; without it attached images become a text placeholder.
    supports_vision: bool
    # List prices (Anthropic first-party rates), None when unknown — cost estimates only.
    input_usd_per_mtok: float | None
    output_usd_per_mtok: float | None
    cache_read_multiplier: float
    is_default: bool


@dataclass(frozen=True, slots=True)
class _Known:
    display_name: str
    tier: Tier
    input_usd: float
    output_usd: float
    cache_read_multiplier: float = 0.1


# Current and still-served Claude models; an id outside this table is accepted with defaults so a
# newer release never needs a code change.
_KNOWN_ANTHROPIC: dict[str, _Known] = {
    "claude-opus-5-5": _Known("Claude Opus 5.5", "frontier", 4.0, 20.0, 0.05),
    "claude-opus-5": _Known("Claude Opus 5", "frontier", 5.0, 25.0),
    "claude-opus-4-8": _Known("Claude Opus 4.8", "frontier", 5.0, 25.0),
    "claude-sonnet-5-5": _Known("Claude Sonnet 5.5", "balanced", 2.0, 10.0),
    "claude-sonnet-5": _Known("Claude Sonnet 5", "balanced", 2.0, 10.0),
    "claude-sonnet-4-6": _Known("Claude Sonnet 4.6", "balanced", 3.0, 15.0),
    "claude-haiku-5-5": _Known("Claude Haiku 5.5", "fast", 0.10, 0.50),
    "claude-haiku-4-5": _Known("Claude Haiku 4.5", "fast", 1.0, 5.0),
}


def _display_name(model_id: str) -> str:
    return " ".join(part.capitalize() for part in model_id.replace("_", "-").split("-"))


def _openai_tier(model_id: str) -> Tier:
    """OpenAI-style naming: `-mini` / `-nano` variants are the fast tier, `-pro` the frontier."""
    if model_id.endswith(("-mini", "-nano")):
        return "fast"
    if model_id.endswith("-pro"):
        return "frontier"
    return "balanced"


class ModelCatalog:
    def __init__(
        self,
        *,
        model_ids: Sequence[str],
        default_id: str,
        title_id: str,
        anthropic_configured: bool,
        openai_configured: bool,
        openai_supports_tools: bool,
        openai_supports_reasoning: bool,
        openai_supports_vision: bool,
    ) -> None:
        self._configured: dict[LlmProvider, bool] = {"anthropic": anthropic_configured, "openai": openai_configured}
        parsed = [(full_id, *parse_model_id(full_id)) for full_id in model_ids]
        # The configured defaults apply only while their provider has credentials; otherwise the
        # first available model (and the first available fast one for titles) steps in, so a
        # single provider key is enough to make the whole app usable.
        available = [full_id for full_id, provider, _ in parsed if self._configured[provider]]
        fast = [
            full_id
            for full_id, provider, model_id in parsed
            if full_id in available and _tier_of(provider, model_id) == "fast"
        ]
        default_id = default_id if default_id in available else (available[0] if available else default_id)
        title_id = title_id if title_id in available else (fast[0] if fast else available[0] if available else title_id)
        self._specs: dict[str, ModelSpec] = {}
        for full_id, provider, model_id in parsed:
            if provider == "anthropic":
                known = _KNOWN_ANTHROPIC.get(model_id)
                spec = ModelSpec(
                    id=full_id,
                    provider=provider,
                    model_id=model_id,
                    display_name=known.display_name if known else _display_name(model_id),
                    tier=known.tier if known else "balanced",
                    supports_tools=True,
                    supports_reasoning=True,
                    supports_vision=True,
                    input_usd_per_mtok=known.input_usd if known else None,
                    output_usd_per_mtok=known.output_usd if known else None,
                    cache_read_multiplier=known.cache_read_multiplier if known else 0.1,
                    is_default=full_id == default_id,
                )
            else:
                spec = ModelSpec(
                    id=full_id,
                    provider=provider,
                    model_id=model_id,
                    display_name=_display_name(model_id),
                    tier=_openai_tier(model_id),
                    supports_tools=openai_supports_tools,
                    supports_reasoning=openai_supports_reasoning,
                    supports_vision=openai_supports_vision,
                    input_usd_per_mtok=None,
                    output_usd_per_mtok=None,
                    cache_read_multiplier=1.0,
                    is_default=full_id == default_id,
                )
            self._specs[full_id] = spec
        self._default_id = default_id
        self._title_id = title_id

    def all(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def available(self) -> list[ModelSpec]:
        """The picker: only models whose provider has credentials."""
        return [spec for spec in self._specs.values() if self._configured[spec.provider]]

    def get(self, model_id: str) -> ModelSpec:
        """Resolve a client-supplied id: 400 when unknown, 503 when its provider is not configured."""
        spec = self._specs.get(model_id)
        if spec is None:
            raise AppError.bad_request("Unknown model", details={"model": model_id})
        if not self._configured[spec.provider]:
            raise AppError.service_unavailable("LLM provider not configured", provider=spec.provider, model=model_id)
        return spec

    def default(self) -> ModelSpec:
        return self._specs[self._default_id]

    def title_model(self) -> ModelSpec:
        return self._specs[self._title_id]

    def cheaper(self, spec: ModelSpec) -> ModelSpec:
        """The same provider one tier down (frontier → balanced → fast), or ``spec`` itself."""
        for tier in _TIER_ORDER[_TIER_ORDER.index(spec.tier) + 1 :]:
            for candidate in self._specs.values():
                if candidate.provider == spec.provider and candidate.tier == tier:
                    return candidate
        return spec


def estimate_cost_usd(
    spec: ModelSpec, *, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0
) -> float | None:
    """List-price cost of a run on ``spec`` (cache reads at the provider's discount), or ``None`` when
    the prices are unknown. An operator's estimate for the logs, never billing."""
    if spec.input_usd_per_mtok is None or spec.output_usd_per_mtok is None:
        return None
    uncached = max(0, input_tokens - cache_read_tokens)
    cached = cache_read_tokens * spec.cache_read_multiplier
    return round(
        ((uncached + cached) * spec.input_usd_per_mtok + output_tokens * spec.output_usd_per_mtok) / 1_000_000, 6
    )


def _tier_of(provider: LlmProvider, model_id: str) -> Tier:
    if provider == "anthropic":
        known = _KNOWN_ANTHROPIC.get(model_id)
        return known.tier if known else "balanced"
    return _openai_tier(model_id)


@cache
def model_catalog() -> ModelCatalog:
    """The catalog built from settings, once per process."""
    return ModelCatalog(
        model_ids=llm_settings.llm_models,
        default_id=llm_settings.llm_default_model,
        title_id=llm_settings.llm_title_model,
        anthropic_configured=llm_settings.anthropic_configured,
        openai_configured=llm_settings.openai_configured,
        openai_supports_tools=llm_settings.llm_openai_supports_tools,
        openai_supports_reasoning=llm_settings.llm_openai_supports_reasoning,
        openai_supports_vision=llm_settings.llm_openai_supports_vision,
    )
