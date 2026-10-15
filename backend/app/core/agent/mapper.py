"""The stream mapper's state machine: which graph event becomes which chunk, and how a run ends."""

# Library boundary: LangGraph's v2 stream events are `dict[str, Any]`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import cast

from pydantic import ValidationError

from app.core.agent.events import MappedEvent, RunFinished, UIChunkEvent
from app.core.agent.parts import PartWriter
from app.core.agent.state import StopInfo
from app.core.agent.steps import on_message_chunk, on_model_update, on_tool_update
from app.core.agent.usage import RunUsage, UsageTotals
from app.core.exceptions import AppError
from app.core.logging_config import get_logger
from app.core.tools.base import SourceRegistry
from app.core.ui_stream import UI_CHUNK_ADAPTER

logger = get_logger(__name__)

DEFAULT_STREAMED_NODES: frozenset[str] = frozenset({"agent", "synthesize"})
TOOL_NODES: frozenset[str] = frozenset({"tools", "budget_exceeded"})


class Mapper:
    def __init__(self, streamed_nodes: Collection[str], *, sources: SourceRegistry | None = None) -> None:
        self._streamed_nodes = set(streamed_nodes)
        self.writer = PartWriter(sources)
        self.usage = RunUsage()
        self.last_stop: StopInfo | None = None
        self._steps_done = 0

    def handle(self, event: Mapping[str, object]) -> list[MappedEvent]:
        kind = event.get("type")
        data = event.get("data")
        if kind == "custom":
            return list(self._on_custom(data))
        if event.get("ns"):  # a nested graph (research subagent): its node reports progress itself
            return []
        if kind == "messages" and isinstance(data, tuple):
            message, metadata = cast("tuple[object, object]", data)
            node = metadata.get("langgraph_node") if isinstance(metadata, Mapping) else None
            if node in self._streamed_nodes:
                return list(on_message_chunk(self.writer, message))
            return []
        if kind == "updates" and isinstance(data, Mapping):
            return self._on_updates(cast("Mapping[str, object]", data))
        return []

    def _on_updates(self, updates: Mapping[str, object]) -> list[MappedEvent]:
        out: list[MappedEvent] = []
        for node, update in updates.items():
            if not isinstance(update, Mapping):
                continue
            update_map = cast("Mapping[str, object]", update)
            stop = update_map.get("stop")
            if isinstance(stop, StopInfo):
                self.last_stop = stop
            if node in TOOL_NODES:
                chunks, step = on_tool_update(self.writer, update_map, self.usage, self._steps_done + 1)
            elif node in self._streamed_nodes:
                chunks, step, self.usage = on_model_update(self.writer, update_map, self.usage, self._steps_done + 1)
            else:
                self._absorb_usage(node, update_map)
                continue
            out.extend(chunks)
            if step is not None:
                self._steps_done += 1
                out.append(step)
        return out

    def _absorb_usage(self, node: str, update: Mapping[str, object]) -> None:
        """Nodes that call models without streaming (research planner, subagents, checker) report usage as a list."""
        usage = update.get("usage")
        if not isinstance(usage, list):
            return
        for item in cast("list[object]", usage):
            if isinstance(item, UsageTotals):
                self.usage = self.usage.add(node, item)

    def _on_custom(self, data: object) -> list[UIChunkEvent]:
        try:
            chunk = UI_CHUNK_ADAPTER.validate_python(data)
        except ValidationError:
            logger.warning("ignoring invalid custom stream chunk", chunk_type=type(data).__name__)
            return []
        return [self.writer.emit(chunk)]

    def finish(self, *, cancelled: bool = False, error: AppError | None = None) -> list[MappedEvent]:
        out: list[MappedEvent] = list(self.writer.finish_step())
        stop = self.last_stop or StopInfo("end")
        if cancelled:
            stop = StopInfo("cancelled")
            out.append(self.writer.emit({"type": "abort", "reason": "cancelled"}))
        elif error is not None:
            stop = StopInfo("error", explanation=error.message)
            out.append(self.writer.emit({"type": "error", "errorText": error.message}))
        elif stop.reason == "error":
            out.append(self.writer.emit({"type": "error", "errorText": stop.explanation or "The assistant failed"}))
        else:
            out.append(self.writer.emit({"type": "finish", "finishReason": stop.finish_reason}))
        out.append(RunFinished(stop=stop, usage=self.usage, parts=self.writer.parts(), error=error))
        return out
