"""Token usage as the worker records it: per model, summed over a run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage


@dataclass(frozen=True, slots=True)
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def __add__(self, other: UsageTotals) -> UsageTotals:
        return UsageTotals(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def usage_of(message: AIMessage) -> UsageTotals:
    """The usage a provider reported on ``message`` (zeros when it reported none)."""
    usage = message.usage_metadata
    if usage is None:
        return UsageTotals()
    details = usage.get("input_token_details") or {}
    return UsageTotals(
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_read_tokens=details.get("cache_read", 0),
        cache_creation_tokens=details.get("cache_creation", 0),
    )


def model_name_of(message: AIMessage) -> str:
    name = message.response_metadata.get("model_name") or message.response_metadata.get("model")
    return name if isinstance(name, str) and name else "unknown"


def _no_usage() -> dict[str, UsageTotals]:
    return {}


@dataclass(frozen=True, slots=True)
class RunUsage:
    """Totals for a run plus a breakdown by model name (or by graph node for unstreamed calls)."""

    total: UsageTotals = UsageTotals()
    by_model: Mapping[str, UsageTotals] = field(default_factory=_no_usage)

    def add(self, model: str, usage: UsageTotals) -> RunUsage:
        by_model: dict[str, UsageTotals] = dict(self.by_model)
        by_model[model] = by_model.get(model, UsageTotals()) + usage
        return RunUsage(total=self.total + usage, by_model=by_model)
