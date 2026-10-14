"""Web search and page extraction — the Tavily adapter behind the ``SearchClient`` seam.

``web_search`` and ``web_fetch`` depend on the Protocol only; ``TavilySearchClient`` talks to
``https://api.tavily.com`` over one lazily created ``httpx.AsyncClient`` with a concurrency cap,
and translates HTTP failures to ``AppError`` so nothing else knows Tavily's status codes. Without
``TAVILY_API_KEY`` there is no client and the web tools are not offered to the model.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Literal, Protocol, cast

import httpx

from app.core.config import search_settings
from app.core.exceptions import AppError
from app.core.logging_config import get_logger
from app.core.ui_stream import JsonObject

logger = get_logger(__name__)

TAVILY_BASE_URL = "https://api.tavily.com"
type SearchTopic = Literal["general", "news", "finance"]
type SearchRecency = Literal["day", "week", "month", "year"]
type ExtractDepth = Literal["basic", "advanced"]
# Tavily's own rate-limit codes: 429 (requests), 432 (plan usage), 433 (key usage).
_BUSY_STATUSES = frozenset({429, 432, 433})


@dataclass(frozen=True, slots=True)
class SearchQuery:
    query: str
    max_results: int = 5
    topic: SearchTopic = "general"
    recency: SearchRecency | None = None
    include_domains: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    published_at: str | None
    score: float | None


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    url: str
    title: str | None
    content: str


class SearchClient(Protocol):
    async def search(self, query: SearchQuery) -> list[SearchResult]: ...

    async def extract(
        self, urls: Sequence[str], *, query: str | None = None, depth: ExtractDepth = "basic"
    ) -> tuple[list[ExtractedPage], list[str]]:
        """Readable page content for ``urls`` → ``(pages, failed_urls)``."""
        ...


# ── Tavily ───────────────────────────────────────────────────────────────────


def _translate_status(response: httpx.Response) -> AppError:
    status = response.status_code
    if status in (401, 403):
        return AppError.internal("Search provider misconfigured", tavily_status=status)
    if status in _BUSY_STATUSES:
        retry_after = response.headers.get("retry-after")
        return AppError.service_unavailable(
            "Search provider is busy, please retry", tavily_status=status, retry_after=retry_after
        )
    if status in (400, 422):
        return AppError.bad_request("Search request rejected", tavily_status=status)
    if status >= 500:
        return AppError.service_unavailable("Search provider unavailable", tavily_status=status)
    return AppError.internal("Search provider error", tavily_status=status)


def _str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _dict_items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    items: list[object] = list(value)  # pyright: ignore[reportUnknownArgumentType] — JSON from the wire
    return [cast("Mapping[str, object]", item) for item in items if isinstance(item, Mapping)]


class TavilySearchClient:
    """``SearchClient`` over the Tavily REST API."""

    def __init__(
        self,
        *,
        api_key: str,
        max_concurrency: int = 8,
        timeout_s: float = 30.0,
        base_url: str = TAVILY_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._base_url = base_url
        self._transport = transport
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_s,
                headers={"Authorization": f"Bearer {self._api_key}"},
                transport=self._transport,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _post(self, path: str, payload: JsonObject) -> Mapping[str, object]:
        async with self._semaphore:
            try:
                response = await self._client().post(path, json=payload)
            except httpx.TimeoutException as error:
                raise AppError.service_unavailable("Search provider timed out", cause=error) from error
            except httpx.TransportError as error:
                raise AppError.service_unavailable("Search provider unreachable", cause=error) from error
        if response.status_code >= 400:
            raise _translate_status(response)
        try:
            body: object = response.json()
        except ValueError as error:
            raise AppError.service_unavailable(
                "Search provider returned an unreadable response", cause=error
            ) from error
        if not isinstance(body, Mapping):
            raise AppError.service_unavailable("Search provider returned an unexpected response")
        return cast("Mapping[str, object]", body)

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        payload: JsonObject = {
            "query": query.query,
            "search_depth": "basic",
            "topic": query.topic,
            "max_results": query.max_results,
        }
        if query.recency is not None:
            payload["time_range"] = query.recency
        if query.include_domains:
            payload["include_domains"] = list(query.include_domains)
        body = await self._post("/search", payload)
        results: list[SearchResult] = []
        for item in _dict_items(body.get("results")):
            url = _str(item.get("url"))
            if not url:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=_str(item.get("title"), default=url),
                    snippet=_str(item.get("content")),
                    published_at=_str(item.get("published_date")) or None,
                    score=_float(item.get("score")),
                )
            )
        logger.info("tavily search", results=len(results))
        return results

    async def extract(
        self, urls: Sequence[str], *, query: str | None = None, depth: ExtractDepth = "basic"
    ) -> tuple[list[ExtractedPage], list[str]]:
        payload: JsonObject = {"urls": list(urls), "extract_depth": depth, "format": "markdown"}
        if query:
            payload["query"] = query
            payload["chunks_per_source"] = 3
        body = await self._post("/extract", payload)
        pages: list[ExtractedPage] = []
        for item in _dict_items(body.get("results")):
            url = _str(item.get("url"))
            if url:
                pages.append(
                    ExtractedPage(url=url, title=_str(item.get("title")) or None, content=_str(item.get("raw_content")))
                )
        failed = [_str(item.get("url")) for item in _dict_items(body.get("failed_results")) if _str(item.get("url"))]
        logger.info("tavily extract", pages=len(pages), failed=len(failed))
        return pages, failed


# ── Wiring ───────────────────────────────────────────────────────────────────


@cache
def default_search_client() -> TavilySearchClient | None:
    """The process search client, or ``None`` when ``TAVILY_API_KEY`` is unset (web tools hidden)."""
    key = search_settings.tavily_api_key
    if key is None:
        logger.info("web search disabled", reason="TAVILY_API_KEY not configured")
        return None
    return TavilySearchClient(
        api_key=key.get_secret_value(),
        max_concurrency=search_settings.search_max_concurrency,
        timeout_s=search_settings.search_timeout_s,
    )


async def close_search_client() -> None:
    """Release the HTTP connection pool at the worker's shutdown."""
    client = default_search_client()
    if client is not None:
        await client.aclose()
