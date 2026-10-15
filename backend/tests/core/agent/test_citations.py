"""The pure citation helpers: URL cleaning, link detection, marker insertion and link numbering."""

from __future__ import annotations

from app.core.agent.citations import UrlCitation, cite_text, clean_url, number_links, span_links
from app.core.agent.server_tools import search_chunks, server_searches
from app.core.tools.base import SourceRegistry
from app.core.ui_stream import UIChunk

DOCS = "https://docs.python.org/3.14/whatsnew/3.14.html"


def test_clean_url_drops_tracking_parameters_only() -> None:
    assert clean_url(f"{DOCS}?utm_source=chatgpt.com") == DOCS
    assert clean_url(f"{DOCS}?utm_source=openai&page=2#top") == f"{DOCS}?page=2#top"
    assert clean_url(DOCS) == DOCS
    assert clean_url(" not a url ") == "not a url"


def test_span_links_recognises_the_models_own_inline_citation() -> None:
    assert span_links(f"fast ([Docs]({DOCS}?utm_source=openai))", DOCS)
    assert not span_links("fast [1]", DOCS)
    assert not span_links(f"see {DOCS}", DOCS)  # a bare URL is not a link
    assert not span_links("([Other](https://other.example/))", DOCS)


def test_cite_text_numbers_in_reading_order_and_marks_only_unlinked_spans() -> None:
    sources = SourceRegistry()
    written: list[UIChunk] = []
    link = f"([Docs]({DOCS}?utm_source=openai))"
    text = f"A is fast {link}. B is cheap. B is cheap again."
    citations = [
        UrlCitation(
            url="https://b.example/", title="B", start=text.index("B is cheap"), end=text.index("B is cheap") + 10
        ),
        UrlCitation(
            url=f"{DOCS}?utm_source=openai", title="Docs", start=text.index(link), end=text.index(link) + len(link)
        ),
        UrlCitation(url="https://b.example/#x", title="B", start=text.index("again") - 11, end=text.index("again") + 5),
    ]
    result = cite_text(text, citations, sources, written.append)
    assert result == f"A is fast {link}. B is cheap [2]. B is cheap again [2]."
    assert [(source.id, source.url) for source in sources.all()] == [(1, DOCS), (2, "https://b.example/")]
    assert [chunk["type"] for chunk in written] == ["source-url", "source-url"]
    # A marker the text already carries is not doubled.
    assert cite_text("Known [1].", [UrlCitation(DOCS, None, 0, 9)], sources, written.append) == "Known [1]."


def test_number_links_turns_links_to_known_sources_into_markers() -> None:
    sources = SourceRegistry()
    sources.add(DOCS, "Docs")
    text = f"A is fast ([Docs]({DOCS}?utm_source=openai)). See [the PEP](https://peps.python.org/pep-0750/)."
    assert number_links(text, sources) == "A is fast [1]. See [the PEP](https://peps.python.org/pep-0750/)."
    assert number_links(f"bare [Docs]({DOCS})", sources) == "bare [1]"


def test_server_searches_read_every_action_shape() -> None:
    content = [
        {"type": "text", "text": "hi"},
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": {
                "type": "search",
                "queries": ["a", "b"],
                "sources": [{"type": "url", "url": f"{DOCS}?utm_source=openai"}],
            },
        },
        {"type": "web_search_call", "id": "ws_2", "status": "completed", "action": {"type": "open_page", "url": DOCS}},
        {
            "type": "web_search_call",
            "id": "ws_3",
            "status": "failed",
            "action": {"type": "find_in_page", "url": DOCS, "pattern": "t-strings"},
        },
        {"type": "web_search_call", "id": "ws_4", "status": "completed"},
        {"type": "web_search_call", "status": "completed"},  # no id: ignored
    ]
    searches = server_searches(content)
    assert [(s.call_id, s.action, s.tool_name, s.query, s.url, s.sources, s.failed) for s in searches] == [
        ("ws_1", "search", "web_search", "a | b", None, (DOCS,), False),
        ("ws_2", "open_page", "web_fetch", None, DOCS, (), False),
        ("ws_3", "find_in_page", "web_fetch", "t-strings", DOCS, (), True),
        ("ws_4", "search", "web_search", None, None, (), False),
    ]
    chunks = search_chunks(searches[2])
    assert [chunk["type"] for chunk in chunks] == ["tool-input-start", "tool-input-available", "tool-output-error"]
    assert chunks[1] == {
        "type": "tool-input-available",
        "toolCallId": "ws_3",
        "toolName": "web_fetch",
        "input": {"url": DOCS, "query": "t-strings"},
        "providerExecuted": True,
    }
    assert dict(search_chunks(searches[3])[1]) == {
        "type": "tool-input-available",
        "toolCallId": "ws_4",
        "toolName": "web_search",
        "input": {"query": ""},
        "providerExecuted": True,
    }
