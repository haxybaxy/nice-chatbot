"""``TavilySearchClient`` over an ``httpx.MockTransport``: request shape, parsing, error translation."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import pytest

from app.core.exceptions import AppError
from app.core.search import SearchQuery, TavilySearchClient, close_search_client, default_search_client

SEARCH_BODY = {
    "query": "python 3.14",
    "results": [
        {
            "title": "What's new",
            "url": "https://docs.python.org/3.14/whatsnew/",
            "content": "t-strings",
            "score": 0.91,
            "published_date": "2026-10-01",
        },
        {"title": "No url here", "content": "skipped"},
        {"url": "https://example.com/untitled", "content": "no title", "score": "bad"},
    ],
}
EXTRACT_BODY = {
    "results": [{"url": "https://a.example/", "raw_content": "# A\n\nbody", "title": "A"}],
    "failed_results": [{"url": "https://b.example/", "error": "timeout"}],
}


@dataclass
class _Server:
    status: int = 200
    body: object = None
    headers: dict[str, str] = field(default_factory=dict)
    raise_error: Exception | None = None
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self) -> Callable[[httpx.Request], httpx.Response]:
        def _handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self.raise_error is not None:
                raise self.raise_error
            content = self.body if isinstance(self.body, str | bytes) else json.dumps(self.body)
            return httpx.Response(self.status, content=content, headers=self.headers)

        return _handle

    def client(self, max_concurrency: int = 8) -> TavilySearchClient:
        return TavilySearchClient(
            api_key="tvly-test", transport=httpx.MockTransport(self.handler()), max_concurrency=max_concurrency
        )

    def last_json(self) -> dict[str, object]:
        return json.loads(self.requests[-1].content)


async def test_search_sends_the_documented_payload_and_parses_results() -> None:
    server = _Server(body=SEARCH_BODY)
    client = server.client(max_concurrency=2)
    results = await client.search(
        SearchQuery(query="python 3.14", max_results=3, topic="news", recency="week", include_domains=("python.org",))
    )
    request = server.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.tavily.com/search"
    assert request.headers["authorization"] == "Bearer tvly-test"
    assert server.last_json() == {
        "query": "python 3.14",
        "search_depth": "basic",
        "topic": "news",
        "max_results": 3,
        "time_range": "week",
        "include_domains": ["python.org"],
    }
    assert len(results) == 2  # the entry without a url is dropped
    assert (results[0].title, results[0].snippet, results[0].score, results[0].published_at) == (
        "What's new",
        "t-strings",
        0.91,
        "2026-10-01",
    )
    assert (results[1].title, results[1].score, results[1].published_at) == ("https://example.com/untitled", None, None)
    await client.aclose()


async def test_search_omits_optional_fields() -> None:
    server = _Server(body={"results": []})
    assert await server.client().search(SearchQuery(query="x")) == []
    assert server.last_json() == {"query": "x", "search_depth": "basic", "topic": "general", "max_results": 5}


async def test_extract_sends_urls_and_separates_failures() -> None:
    server = _Server(body=EXTRACT_BODY)
    pages, failed = await server.client().extract(
        ["https://a.example/", "https://b.example/"], query="A", depth="advanced"
    )
    assert server.last_json() == {
        "urls": ["https://a.example/", "https://b.example/"],
        "extract_depth": "advanced",
        "format": "markdown",
        "query": "A",
        "chunks_per_source": 3,
    }
    assert [(page.url, page.title, page.content) for page in pages] == [("https://a.example/", "A", "# A\n\nbody")]
    assert failed == ["https://b.example/"]
    await server.client().extract(["https://a.example/"])
    assert "query" not in server.last_json()


@pytest.mark.parametrize(
    ("status", "headers", "expected_status", "message"),
    [
        (401, {}, 500, "Search provider misconfigured"),
        (403, {}, 500, "Search provider misconfigured"),
        (429, {"retry-after": "9"}, 503, "Search provider is busy, please retry"),
        (432, {}, 503, "Search provider is busy, please retry"),
        (400, {}, 400, "Search request rejected"),
        (422, {}, 400, "Search request rejected"),
        (500, {}, 503, "Search provider unavailable"),
        (418, {}, 500, "Search provider error"),
    ],
)
async def test_http_errors_become_app_errors(
    status: int, headers: dict[str, str], expected_status: int, message: str
) -> None:
    server = _Server(status=status, body={"detail": "x"}, headers=headers)
    with pytest.raises(AppError) as error:
        await server.client().search(SearchQuery(query="x"))
    assert (error.value.status_code, error.value.message) == (expected_status, message)
    if status == 429:
        assert error.value.context["retry_after"] == "9"


async def test_transport_failures_and_bad_bodies() -> None:
    with pytest.raises(AppError) as timeout:
        await _Server(raise_error=httpx.ReadTimeout("slow")).client().search(SearchQuery(query="x"))
    assert (timeout.value.status_code, timeout.value.message) == (503, "Search provider timed out")
    with pytest.raises(AppError) as unreachable:
        await _Server(raise_error=httpx.ConnectError("refused")).client().search(SearchQuery(query="x"))
    assert (unreachable.value.status_code, unreachable.value.message) == (503, "Search provider unreachable")
    with pytest.raises(AppError) as unreadable:
        await _Server(body="not json").client().search(SearchQuery(query="x"))
    assert unreadable.value.status_code == 503
    with pytest.raises(AppError) as unexpected:
        await _Server(body=[1, 2]).client().search(SearchQuery(query="x"))
    assert unexpected.value.status_code == 503


async def test_default_client_follows_the_test_environment() -> None:
    client = default_search_client()
    assert isinstance(client, TavilySearchClient)
    assert default_search_client() is client
    await close_search_client()
