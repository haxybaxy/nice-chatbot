"""Fold a run's chunk log into the persisted ``message.parts`` (the UI message shape).

Mirrors what ``useChat`` builds client-side from the same stream, so a message loaded over REST
and one rebuilt from a replayed stream are identical. Used by the worker after each step and by
the reaper when it finalizes a lost run from its event log.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import cast

from app.core.ui_stream import (
    DATA_PREFIX,
    TOOL_PREFIX,
    DataChunk,
    JsonObject,
    ReasoningDeltaChunk,
    ReasoningEndChunk,
    ReasoningStartChunk,
    SourceUrlChunk,
    TextDeltaChunk,
    TextEndChunk,
    TextStartChunk,
    ToolInputAvailableChunk,
    ToolInputDeltaChunk,
    ToolInputStartChunk,
    ToolOutputAvailableChunk,
    ToolOutputErrorChunk,
    UIChunk,
)


class _Folder:
    def __init__(self) -> None:
        self.parts: list[JsonObject] = []
        self._by_id: dict[str, JsonObject] = {}  # text/reasoning parts by chunk id
        self._tools: dict[str, JsonObject] = {}  # tool parts by toolCallId
        self._tool_input_text: dict[str, str] = {}
        self._step_starts: list[int] = []  # indexes of step-start parts

    def feed(self, chunk: UIChunk) -> None:
        chunk_type = chunk["type"]
        if chunk_type.startswith(DATA_PREFIX):
            self.data(cast(DataChunk, chunk))
            return
        handler = _HANDLERS.get(chunk_type)
        if handler is not None:
            handler(self, chunk)

    # ── steps ────────────────────────────────────────────────────────────────

    def start_step(self, _chunk: UIChunk) -> None:
        self._step_starts.append(len(self.parts))
        self.parts.append({"type": "step-start"})

    def reset_step(self, _chunk: UIChunk) -> None:
        cut = self._step_starts.pop() if self._step_starts else 0
        dropped = self.parts[cut:]
        del self.parts[cut:]
        for part in dropped:
            self._by_id = {key: value for key, value in self._by_id.items() if value is not part}
            self._tools = {key: value for key, value in self._tools.items() if value is not part}

    # ── text / reasoning ─────────────────────────────────────────────────────

    def open_text(self, chunk: UIChunk) -> None:
        self._open("text", cast(TextStartChunk, chunk)["id"])

    def open_reasoning(self, chunk: UIChunk) -> None:
        self._open("reasoning", cast(ReasoningStartChunk, chunk)["id"])

    def text_delta(self, chunk: UIChunk) -> None:
        delta = cast(TextDeltaChunk, chunk)
        self._append("text", delta["id"], delta["delta"])

    def reasoning_delta(self, chunk: UIChunk) -> None:
        delta = cast(ReasoningDeltaChunk, chunk)
        self._append("reasoning", delta["id"], delta["delta"])

    def close_text(self, chunk: UIChunk) -> None:
        self._close(cast(TextEndChunk, chunk)["id"])

    def close_reasoning(self, chunk: UIChunk) -> None:
        self._close(cast(ReasoningEndChunk, chunk)["id"])

    def _open(self, kind: str, chunk_id: str) -> JsonObject:
        part: JsonObject = {"type": kind, "text": "", "state": "streaming"}
        self._by_id[chunk_id] = part
        self.parts.append(part)
        return part

    def _append(self, kind: str, chunk_id: str, delta: str) -> None:
        # A delta without its start is tolerated, as the client does for replays.
        part = self._by_id.get(chunk_id) or self._open(kind, chunk_id)
        part["text"] = str(part.get("text", "")) + delta

    def _close(self, chunk_id: str) -> None:
        part = self._by_id.get(chunk_id)
        if part is not None:
            part["state"] = "done"

    # ── tools ────────────────────────────────────────────────────────────────

    def _tool_part(self, call_id: str, name: str | None) -> JsonObject:
        part = self._tools.get(call_id)
        if part is None:
            fresh: JsonObject = {
                "type": f"{TOOL_PREFIX}{name or 'unknown'}",
                "toolCallId": call_id,
                "state": "input-streaming",
            }
            part = fresh
            self._tools[call_id] = part
            self.parts.append(part)
        return part

    def tool_input_start(self, chunk: UIChunk) -> None:
        start = cast(ToolInputStartChunk, chunk)
        self._tool_part(start["toolCallId"], start["toolName"])

    def tool_input_delta(self, chunk: UIChunk) -> None:
        delta = cast(ToolInputDeltaChunk, chunk)
        call_id = delta["toolCallId"]
        self._tool_part(call_id, None)
        self._tool_input_text[call_id] = self._tool_input_text.get(call_id, "") + delta["inputTextDelta"]

    def tool_input_available(self, chunk: UIChunk) -> None:
        available = cast(ToolInputAvailableChunk, chunk)
        part = self._tool_part(available["toolCallId"], available["toolName"])
        part["type"] = f"{TOOL_PREFIX}{available['toolName']}"
        part["state"] = "input-available"
        part["input"] = available["input"]

    def tool_output_available(self, chunk: UIChunk) -> None:
        output = cast(ToolOutputAvailableChunk, chunk)
        part = self._tool_part(output["toolCallId"], None)
        part["state"] = "output-available"
        part["output"] = output["output"]

    def tool_output_error(self, chunk: UIChunk) -> None:
        error = cast(ToolOutputErrorChunk, chunk)
        part = self._tool_part(error["toolCallId"], None)
        part["state"] = "output-error"
        part["errorText"] = error["errorText"]

    # ── sources / data ───────────────────────────────────────────────────────

    def source_url(self, chunk: UIChunk) -> None:
        source = cast(SourceUrlChunk, chunk)
        part: JsonObject = {"type": "source-url", "sourceId": source["sourceId"], "url": source["url"]}
        title = source.get("title")
        if title:
            part["title"] = title
        self.parts.append(part)

    def data(self, chunk: DataChunk) -> None:
        if chunk.get("transient"):
            return
        part_id = chunk.get("id")
        part: JsonObject = {"type": chunk["type"], "data": chunk["data"]}
        if part_id is not None:
            part["id"] = part_id
            for index, existing in enumerate(self.parts):
                if existing.get("type") == chunk["type"] and existing.get("id") == part_id:
                    self.parts[index] = part
                    return
        self.parts.append(part)

    def finalize(self) -> list[JsonObject]:
        """Persisted parts never carry ``input-streaming``: settle it with the best-effort input."""
        for call_id, part in self._tools.items():
            if part.get("state") == "input-streaming":
                part["state"] = "input-available"
                part["input"] = _parse_partial_json(self._tool_input_text.get(call_id, ""))
        for part in self._by_id.values():
            part["state"] = "done"
        return self.parts


_HANDLERS: dict[str, Callable[[_Folder, UIChunk], None]] = {
    "start-step": _Folder.start_step,
    "reset-step": _Folder.reset_step,
    "text-start": _Folder.open_text,
    "text-delta": _Folder.text_delta,
    "text-end": _Folder.close_text,
    "reasoning-start": _Folder.open_reasoning,
    "reasoning-delta": _Folder.reasoning_delta,
    "reasoning-end": _Folder.close_reasoning,
    "tool-input-start": _Folder.tool_input_start,
    "tool-input-delta": _Folder.tool_input_delta,
    "tool-input-available": _Folder.tool_input_available,
    "tool-output-available": _Folder.tool_output_available,
    "tool-output-error": _Folder.tool_output_error,
    "source-url": _Folder.source_url,
}


def _parse_partial_json(text: str) -> object:
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {"partial": text}


def fold_parts(chunks: Iterable[UIChunk]) -> list[JsonObject]:
    """Replay ``chunks`` into the parts list the UI would have built from them."""
    folder = _Folder()
    for chunk in chunks:
        folder.feed(chunk)
    return folder.finalize()
