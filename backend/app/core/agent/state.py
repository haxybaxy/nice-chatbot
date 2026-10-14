"""State, limits and stop information shared by the chat and research graphs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.graph import MessagesState  # pyright: ignore[reportMissingTypeStubs] — no py.typed

from app.core.config import agent_settings

type StopReason = Literal["end", "refusal", "length", "step_limit", "cancelled", "error"]
# Anthropic `stop_reason` / OpenAI `finish_reason` → StopReason; a tool-call stop means "keep going".
_ANTHROPIC_STOPS: dict[str, StopReason] = {
    "end_turn": "end",
    "stop_sequence": "end",
    "pause_turn": "end",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "refusal": "refusal",
}
_OPENAI_STOPS: dict[str, StopReason] = {"stop": "end", "length": "length", "content_filter": "refusal"}
FINISH_REASONS: dict[StopReason, str] = {
    "end": "stop",
    "length": "length",
    "refusal": "content-filter",
    "step_limit": "other",
    "cancelled": "other",
    "error": "error",
}


@dataclass(frozen=True, slots=True)
class StopInfo:
    """Why a run ended, as the UI and the run row record it."""

    reason: StopReason
    explanation: str | None = None

    @property
    def finish_reason(self) -> str:
        """The AI SDK ``finish.finishReason`` value."""
        return FINISH_REASONS[self.reason]


@dataclass(frozen=True, slots=True)
class AgentLimits:
    max_model_calls: int = 12
    max_tool_calls: int = 24
    max_tool_calls_per_step: int = 8

    @property
    def recursion_limit(self) -> int:
        """LangGraph's ``recursion_limit`` for a loop bounded by these limits."""
        return 2 * self.max_model_calls + 4

    @classmethod
    def from_settings(cls) -> AgentLimits:
        return cls(
            max_model_calls=agent_settings.agent_max_model_calls,
            max_tool_calls=agent_settings.agent_max_tool_calls,
            max_tool_calls_per_step=agent_settings.agent_max_tool_calls_per_step,
        )


class AgentState(MessagesState, total=False):
    model_calls: int
    tool_calls_made: int
    final_answer_only: bool
    stop: StopInfo | None


def stop_info_for(message: AIMessage) -> StopInfo | None:
    """The stop the provider reported on ``message``, or ``None`` when the loop should continue."""
    metadata = message.response_metadata
    stop_reason = metadata.get("stop_reason")
    if isinstance(stop_reason, str):
        reason = _ANTHROPIC_STOPS.get(stop_reason)
        return StopInfo(reason) if reason is not None else None
    finish_reason = metadata.get("finish_reason")
    if isinstance(finish_reason, str):
        reason = _OPENAI_STOPS.get(finish_reason)
        return StopInfo(reason) if reason is not None else None
    # No provider metadata (a fake, or a provider that reports nothing): tool calls mean "continue".
    return None if message.tool_calls else StopInfo("end")
