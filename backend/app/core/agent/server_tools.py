"""Provider-executed web search as the UI sees it: the ``web_search_call`` blocks.

OpenAI's built-in ``web_search`` runs inside one model call and leaves a ``web_search_call`` block
per action in the message content — a search with its queries and the pages it consulted, or a page
the model opened. None of it is a LangChain tool call, so the graph never runs a tool node for it;
this module turns those blocks into the ``tool-web_search`` / ``tool-web_fetch`` chunks the UI
already renders, marked ``providerExecuted`` so nothing ever tries to replay them as tool calls.
The citations on the text are ``citations.py``'s business.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from app.core.agent.citations import blocks_of, clean_url
from app.core.ui_stream import JsonObject, UIChunk

type SearchAction = Literal["search", "open_page", "find_in_page"]

WEB_SEARCH_CALL = "web_search_call"
_ACTIONS: frozenset[str] = frozenset({"search", "open_page", "find_in_page"})


@dataclass(frozen=True, slots=True)
class ServerSearch:
    """One ``web_search_call`` block: what the provider did on the model's behalf."""

    call_id: str
    action: SearchAction
    query: str | None
    url: str | None
    sources: tuple[str, ...]
    failed: bool

    @property
    def tool_name(self) -> str:
        """The wire name the UI renders it under: a search, or a page read (``web_fetch``)."""
        return "web_search" if self.action == "search" else "web_fetch"


def server_searches(content: object) -> list[ServerSearch]:
    """The ``web_search_call`` blocks of a message or chunk, in order."""
    searches: list[ServerSearch] = []
    for block in blocks_of(content):
        if block.get("type") != WEB_SEARCH_CALL:
            continue
        call_id = block.get("id")
        if not isinstance(call_id, str) or not call_id:
            continue
        raw_action = block.get("action")
        action: Mapping[str, object] = (
            cast("Mapping[str, object]", raw_action) if isinstance(raw_action, Mapping) else {}
        )
        kind = action.get("type")
        searches.append(
            ServerSearch(
                call_id=call_id,
                action=cast(SearchAction, kind) if isinstance(kind, str) and kind in _ACTIONS else "search",
                query=_query_of(action),
                url=_text(action.get("url")),
                sources=_sources_of(action),
                failed=block.get("status") == "failed",
            )
        )
    return searches


def search_chunks(call: ServerSearch) -> list[UIChunk]:
    """The tool chunks for one server search: announced, with its input, settled with output or error."""
    chunks: list[UIChunk] = [
        {"type": "tool-input-start", "toolCallId": call.call_id, "toolName": call.tool_name, "providerExecuted": True},
        {
            "type": "tool-input-available",
            "toolCallId": call.call_id,
            "toolName": call.tool_name,
            "input": _input_of(call),
            "providerExecuted": True,
        },
    ]
    if call.failed:
        chunks.append(
            {
                "type": "tool-output-error",
                "toolCallId": call.call_id,
                "errorText": "The web search failed.",
                "providerExecuted": True,
            }
        )
    else:
        chunks.append(
            {
                "type": "tool-output-available",
                "toolCallId": call.call_id,
                "output": _output_of(call),
                "providerExecuted": True,
            }
        )
    return chunks


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _query_of(action: Mapping[str, object]) -> str | None:
    queries = action.get("queries")
    if isinstance(queries, list):
        joined = " | ".join(str(query) for query in cast("list[object]", queries) if str(query))
        if joined:
            return joined
    return _text(action.get("query")) or _text(action.get("pattern"))


def _sources_of(action: Mapping[str, object]) -> tuple[str, ...]:
    raw = action.get("sources")
    if not isinstance(raw, list):
        return ()
    urls: list[str] = []
    for item in cast("list[object]", raw):
        url = cast("Mapping[str, object]", item).get("url") if isinstance(item, Mapping) else None
        if isinstance(url, str) and url:
            urls.append(clean_url(url))
    return tuple(urls)


def _input_of(call: ServerSearch) -> JsonObject:
    if call.action == "search":
        return {"query": call.query or ""}
    web_fetch_input: JsonObject = {"url": call.url or ""}
    if call.action == "find_in_page" and call.query:
        web_fetch_input["query"] = call.query
    return web_fetch_input


def _output_of(call: ServerSearch) -> JsonObject:
    """``WebSearchOut`` / ``WebFetchOut``-shaped (camelCase) payloads with what the provider disclosed."""
    if call.action == "search":
        results: list[JsonObject] = [{"url": url, "title": None, "snippet": ""} for url in call.sources]
        return {"query": call.query or "", "results": results}
    return {"sourceId": None, "url": call.url or "", "title": None, "content": "", "chars": 0, "truncated": False}
