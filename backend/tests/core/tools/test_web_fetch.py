"""``web_fetch``: URL policy, extraction through the client, truncation, the page as a source."""

from __future__ import annotations

from typing import cast

import pytest

from app.core.search import ExtractedPage
from app.core.tools.base import ToolInputError
from app.core.tools.web_fetch import validate_fetch_url
from tests.fakes_llm import FakeSearchClient, make_run_context, scripted_turn
from tests.graph_harness import chat_graph, collect, prompt, scripted_model, tools_for

URL = "https://docs.python.org/3.14/whatsnew/"


class TestUrlPolicy:
    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/x",
            "http://localhost:8000/",
            "http://127.0.0.1/",
            "http://[::1]/",
            "http://169.254.169.254/latest/meta-data/",
            "http://intranet/",
            "http://db.internal/",
            "not a url",
        ],
    )
    def test_rejects_non_public_targets(self, url: str) -> None:
        with pytest.raises(ToolInputError):
            validate_fetch_url(url)

    def test_accepts_public_http_urls(self) -> None:
        assert validate_fetch_url("  https://example.com/a?b=1 ") == "https://example.com/a?b=1"
        assert validate_fetch_url("http://sub.example.org") == "http://sub.example.org"


async def test_fetch_registers_the_page_as_a_source_and_truncates() -> None:
    search = FakeSearchClient(pages={URL: ExtractedPage(url=URL, title="What's new", content="word " * 400)})
    ctx = make_run_context(search=search)
    turn = scripted_turn(tool_calls=[("web_fetch", {"url": URL, "max_chars": 500, "query": "t-strings"})])
    model, built = scripted_model([turn, scripted_turn("Summary [1].")])
    result = await collect(chat_graph(built, tools_for(ctx, {"web_fetch"})), ctx, prompt())

    assert search.extracts == [([URL], "t-strings", "basic")]
    content = str(model.calls[1][-1].content)
    assert content.startswith(f"[1] What's new — {URL}\n\n")
    assert content.rstrip().endswith("[truncated — ask for a later section with a query]")
    output = cast("dict[str, object]", result.first("tool-output-available")["output"])
    assert (output["sourceId"], output["url"], output["title"], output["truncated"]) == ("1", URL, "What's new", True)
    assert output["chars"] == len(str(output["content"])) <= 500
    assert result.first("source-url") == {"type": "source-url", "sourceId": "1", "url": URL, "title": "What's new"}
    assert result.first("data-tool-progress")["data"] == {
        "toolCallId": turn.tool_calls[0]["id"],
        "status": "fetching",
        "url": URL,
    }


async def test_failed_extraction_and_bad_url_are_tool_errors() -> None:
    search = FakeSearchClient()
    ctx = make_run_context(search=search)
    turns = [
        scripted_turn(tool_calls=[("web_fetch", {"url": URL}), ("web_fetch", {"url": "http://localhost/secret"})]),
        scripted_turn("could not read"),
    ]
    _, built = scripted_model(turns)
    result = await collect(chat_graph(built, tools_for(ctx, {"web_fetch"})), ctx, prompt())
    errors = {str(chunk["toolCallId"]): str(chunk["errorText"]) for chunk in result.of_type("tool-output-error")}
    assert (
        errors[str(turns[0].tool_calls[0]["id"])]
        == "Tool failed: The page could not be fetched or has no readable text"
    )
    assert errors[str(turns[0].tool_calls[1]["id"])] == "url must point at a public host"
    # The blocked URL never reached the client.
    assert search.extracts == [([URL], None, "basic")]
    assert result.of_type("source-url") == []
