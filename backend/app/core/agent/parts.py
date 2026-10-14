"""The chunk writer behind the stream mapper: steps, text/reasoning parts and tool-input streaming.

Keeps the ids of the parts that are open and appends every chunk it emits to ``chunks`` so the
persisted parts can be folded from them at any step boundary.
"""

from __future__ import annotations

import uuid
from typing import Literal

from app.core.agent.events import UIChunkEvent
from app.core.ui_fold import fold_parts
from app.core.ui_stream import JsonObject, UIChunk


class PartWriter:
    def __init__(self) -> None:
        self.chunks: list[UIChunk] = []
        self.step_open = False
        self.streamed_in_step = False
        self.started_calls: set[str] = set()
        self.calls_by_index: dict[int, str] = {}
        self._text_id: str | None = None
        self._reasoning_id: str | None = None

    def emit(self, chunk: UIChunk) -> UIChunkEvent:
        self.chunks.append(chunk)
        return UIChunkEvent(chunk)

    def parts(self) -> list[JsonObject]:
        return fold_parts(self.chunks)

    def open_step(self) -> list[UIChunkEvent]:
        self.step_open = True
        self.streamed_in_step = False
        self.calls_by_index.clear()
        return [self.emit({"type": "start-step"})]

    def close_text(self) -> list[UIChunkEvent]:
        out: list[UIChunkEvent] = []
        if self._text_id is not None:
            out.append(self.emit({"type": "text-end", "id": self._text_id}))
            self._text_id = None
        if self._reasoning_id is not None:
            out.append(self.emit({"type": "reasoning-end", "id": self._reasoning_id}))
            self._reasoning_id = None
        return out

    def delta(self, kind: Literal["text", "reasoning"], text: str) -> list[UIChunkEvent]:
        if kind == "text":
            return self._text_delta(text)
        return self._reasoning_delta(text)

    def _text_delta(self, text: str) -> list[UIChunkEvent]:
        out: list[UIChunkEvent] = []
        if self._text_id is None:
            out.extend(self.close_text())
            self._text_id = uuid.uuid4().hex
            out.append(self.emit({"type": "text-start", "id": self._text_id}))
        out.append(self.emit({"type": "text-delta", "id": self._text_id, "delta": text}))
        return out

    def _reasoning_delta(self, text: str) -> list[UIChunkEvent]:
        out: list[UIChunkEvent] = []
        if self._reasoning_id is None:
            out.extend(self.close_text())
            self._reasoning_id = uuid.uuid4().hex
            out.append(self.emit({"type": "reasoning-start", "id": self._reasoning_id}))
        out.append(self.emit({"type": "reasoning-delta", "id": self._reasoning_id, "delta": text}))
        return out

    def tool_start(self, call_id: str, name: str) -> list[UIChunkEvent]:
        out = self.close_text()
        self.started_calls.add(call_id)
        out.append(self.emit({"type": "tool-input-start", "toolCallId": call_id, "toolName": name}))
        return out

    def finish_step(self) -> list[UIChunkEvent]:
        out = self.close_text()
        if self.step_open:
            out.append(self.emit({"type": "finish-step"}))
            self.step_open = False
        return out
