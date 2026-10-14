"""What ``map_graph_stream`` yields: wire chunks, step completions and the final result of a run."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import BaseMessage

from app.core.agent.state import StopInfo
from app.core.agent.usage import RunUsage
from app.core.exceptions import AppError
from app.core.ui_stream import JsonObject, UIChunk


@dataclass(frozen=True, slots=True)
class UIChunkEvent:
    chunk: UIChunk


@dataclass(frozen=True, slots=True)
class StepCompleted:
    kind: Literal["assistant", "tool"]
    # The LangChain messages this step added (append to `provider_messages` via `dump_turn`).
    messages: Sequence[BaseMessage]
    # Every UI part of the assistant message so far (persist as `message.parts`).
    parts: Sequence[JsonObject]
    usage: RunUsage
    step: int


@dataclass(frozen=True, slots=True)
class RunFinished:
    stop: StopInfo
    usage: RunUsage
    parts: Sequence[JsonObject]
    error: AppError | None = None

    @property
    def finish_reason(self) -> str:
        return self.stop.finish_reason


type MappedEvent = UIChunkEvent | StepCompleted | RunFinished
