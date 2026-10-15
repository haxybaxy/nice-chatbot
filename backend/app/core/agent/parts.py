"""The chunk writer behind the stream mapper: steps, text/reasoning parts, tool-input streaming,
and what a provider-executed search adds — its tool chunks and its citations.

Keeps the ids of the parts that are open and appends every chunk it emits to ``chunks`` so the
persisted parts can be folded from them at any step boundary. Citations are numbered through the
run's :class:`SourceRegistry` so a built-in search and the Tavily tools share one ``[n]`` space.
"""

from __future__ import annotations

import uuid
from typing import Literal

from app.core.agent.citations import UrlCitation, blocks_of, cite_content, marker, register, span_links
from app.core.agent.content import fragments
from app.core.agent.events import UIChunkEvent
from app.core.agent.server_tools import WEB_SEARCH_CALL, ServerSearch, search_chunks, server_searches
from app.core.tools.base import SourceRegistry
from app.core.ui_fold import fold_parts
from app.core.ui_stream import JsonObject, UIChunk

# Characters of the open text part kept to see what a streamed citation refers to.
_TAIL = 400


class PartWriter:
    def __init__(self, sources: SourceRegistry | None = None) -> None:
        self.chunks: list[UIChunk] = []
        self.sources = sources if sources is not None else SourceRegistry()
        self.step_open = False
        self.streamed_in_step = False
        self.started_calls: set[str] = set()
        self.calls_by_index: dict[int, str] = {}
        self._text_id: str | None = None
        self._reasoning_id: str | None = None
        self._text_tail = ""

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
            self._text_tail = ""
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
        self._text_tail = (self._text_tail + text)[-_TAIL:]
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

    # ── Provider-executed search ─────────────────────────────────────────────

    def cite(self, citation: UrlCitation) -> list[UIChunkEvent]:
        """A citation that arrived while the text streams: number the source (``source-url`` once) and,
        unless the text just written already links to it or carries its marker, append `` [n]``."""
        out: list[UIChunkEvent] = []
        source_id = register(self.sources, citation, lambda chunk: out.append(self.emit(chunk)))
        text_marker = marker(source_id)
        if span_links(self._text_tail, citation.url) or self._text_tail.rstrip().endswith(text_marker):
            return out
        # Keep one space around the marker whichever side the stream left it on.
        delta = f"{text_marker} " if self._text_tail.endswith((" ", "\n", "\t")) else f" {text_marker}"
        out.extend(self._text_delta(delta))
        return out

    def server_search(self, call: ServerSearch) -> list[UIChunkEvent]:
        """A ``web_search_call`` block: the tool chunks of a provider-executed search, once per call id."""
        if call.call_id in self.started_calls:
            return []
        out = self.close_text()
        self.started_calls.add(call.call_id)
        out.extend(self.emit(chunk) for chunk in search_chunks(call))
        return out

    def landed_text(self, content: object) -> list[UIChunkEvent]:
        """The text of a message that did not stream, its citations marked at their exact offsets."""
        out: list[UIChunkEvent] = []
        text = cite_content(content, self.sources, lambda chunk: out.append(self.emit(chunk)))
        if text:
            out.extend(self._text_delta(text))
        return out

    def landed_content(self, content: object) -> list[UIChunkEvent]:
        """A message that did not stream, block by block: searches, cited text, reasoning."""
        out: list[UIChunkEvent] = []
        for block in blocks_of(content):
            if block.get("type") == WEB_SEARCH_CALL:
                for search in server_searches([block]):
                    out.extend(self.server_search(search))
            elif block.get("type") == "text":
                out.extend(self.landed_text([block]))
            else:
                for kind, text in fragments([block]):
                    out.extend(self.delta(kind, text))
        return out
