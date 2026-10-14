"""``web_search`` through the real graph: numbered sources, ``source-url`` once per URL, progress, output shape."""

from __future__ import annotations

from app.core.exceptions import AppError
from app.core.search import SearchResult
from tests.fakes_llm import FakeSearchClient, FakeTracer, make_run_context, scripted_turn
from tests.graph_harness import chat_graph, collect, prompt, scripted_model, tools_for

RESULTS = [
    SearchResult(
        url="https://docs.python.org/3.14/whatsnew/",
        title="What's new in 3.14",
        snippet="Python 3.14 adds...",
        published_at="2026-10-01",
        score=0.9,
    ),
    SearchResult(
        url="https://peps.python.org/pep-0750/",
        title="PEP 750",
        snippet="Template strings",
        published_at=None,
        score=0.8,
    ),
]


async def test_search_numbers_sources_and_renders_them_for_model_and_ui() -> None:
    tracer = FakeTracer()
    search = FakeSearchClient(results={"python 3.14": RESULTS, "python 3.14 again": RESULTS[:1]})
    ctx = make_run_context(search=search, tracer=tracer)
    turn_1 = scripted_turn(
        tool_calls=[("web_search", {"query": "python 3.14", "max_results": 3, "topic": "news", "recency": "month"})]
    )
    turn_2 = scripted_turn(tool_calls=[("web_search", {"query": "python 3.14 again"})])
    model, built = scripted_model([turn_1, turn_2, scripted_turn("Python 3.14 adds t-strings [1][2].")])
    result = await collect(chat_graph(built, tools_for(ctx, {"web_search"})), ctx, prompt())

    # The client got the validated query; defaults filled in.
    assert search.queries[0].query == "python 3.14"
    assert (search.queries[0].max_results, search.queries[0].topic, search.queries[0].recency) == (3, "news", "month")
    assert search.queries[1].max_results == 5
    # The model reads numbered results; the second search re-uses [1] for the same URL.
    content = str(model.calls[1][-1].content)
    assert content.startswith('Search results for "python 3.14" (2). Cite as [n].')
    assert "[1] What's new in 3.14 — https://docs.python.org/3.14/whatsnew/ (2026-10-01)" in content
    assert "[2] PEP 750 — https://peps.python.org/pep-0750/" in content
    assert "[1] What's new in 3.14" in str(model.calls[2][-1].content)
    # Each new source is streamed exactly once; progress is transient and keyed by the call id.
    sources = result.of_type("source-url")
    assert [source["sourceId"] for source in sources] == ["1", "2"]
    assert sources[0] == {"type": "source-url", "sourceId": "1", "url": RESULTS[0].url, "title": RESULTS[0].title}
    progress = result.of_type("data-tool-progress")
    assert progress[0]["transient"] is True
    assert progress[0]["id"] == turn_1.tool_calls[0]["id"]
    assert progress[0]["data"] == {
        "toolCallId": turn_1.tool_calls[0]["id"],
        "status": "searching",
        "query": "python 3.14",
    }
    # The UI output is camelCase and carries the source ids.
    output = result.first("tool-output-available")["output"]
    assert isinstance(output, dict)
    assert output["query"] == "python 3.14"
    assert output["results"][0] == {
        "sourceId": "1",
        "title": "What's new in 3.14",
        "url": RESULTS[0].url,
        "snippet": "Python 3.14 adds...",
        "publishedAt": "2026-10-01",
        "score": 0.9,
    }
    # Persisted parts keep the sources in order, and the Tavily call was traced.
    assert [part["sourceId"] for part in result.finished.parts if part["type"] == "source-url"] == ["1", "2"]
    assert [span.name for span in tracer.spans] == ["tavily.search", "tavily.search"]
    assert tracer.spans[0].kind == "retriever"
    assert tracer.spans[0].updates == [{"output": {"results": 2}, "level": None, "status_message": None}]
    assert len(ctx.sources) == 2


async def test_no_results_and_provider_failure() -> None:
    search = FakeSearchClient()
    ctx = make_run_context(search=search)
    turn = scripted_turn(tool_calls=[("web_search", {"query": "nothing here"})])
    model, built = scripted_model([turn, scripted_turn("nothing")])
    await collect(chat_graph(built, tools_for(ctx, {"web_search"})), ctx, prompt())
    assert str(model.calls[1][-1].content).startswith('No results for "nothing here".')

    search.error = AppError.service_unavailable("Search provider is busy, please retry")
    ctx = make_run_context(search=search)
    model, built = scripted_model([scripted_turn(tool_calls=[("web_search", {"query": "x"})]), scripted_turn("sorry")])
    result = await collect(chat_graph(built, tools_for(ctx, {"web_search"})), ctx, prompt())
    assert result.first("tool-output-error")["errorText"] == "Tool failed: Search provider is busy, please retry"
    assert result.finished.stop.reason == "end"


async def test_invalid_arguments_are_rejected_before_the_client_is_called() -> None:
    search = FakeSearchClient()
    ctx = make_run_context(search=search)
    turn = scripted_turn(tool_calls=[("web_search", {"query": "x", "max_results": 50})])
    _, built = scripted_model([turn, scripted_turn("ok")])
    result = await collect(chat_graph(built, tools_for(ctx, {"web_search"})), ctx, prompt())
    assert "max_results" in str(result.first("tool-output-error")["errorText"])
    assert search.queries == []
