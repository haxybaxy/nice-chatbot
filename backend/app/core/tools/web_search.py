"""``web_search`` — Tavily search behind ``SearchClient``; results are numbered sources ``[n]``."""

from __future__ import annotations

from app.core.exceptions import AppError
from app.core.search import SearchQuery
from app.core.tools.base import Tool, ToolCallContext, ToolResult, ToolSpec
from app.core.tools.schemas import WebSearchIn, WebSearchOut, WebSearchResultOut
from app.core.ui_stream import JsonObject, data_chunk, source_url_chunk

DESCRIPTION = (
    "Search the web. Use it when the answer depends on current events, facts you are unsure about, "
    "prices, versions, documentation, or anything after your training data. Results are numbered "
    "sources: cite them as [n] right after the claim they support. Prefer one focused query per "
    "sub-question; follow up with web_fetch to read a result in full."
)


def _format_result(source_id: int, title: str, url: str, snippet: str, published_at: str | None) -> str:
    when = f" ({published_at})" if published_at else ""
    body = f"\n    {snippet.strip()}" if snippet.strip() else ""
    return f"[{source_id}] {title} — {url}{when}{body}"


async def _run(call: ToolCallContext, args: WebSearchIn) -> ToolResult:
    ctx = call.ctx
    if ctx.search is None:
        raise AppError.service_unavailable("Web search is not configured")
    call.write(
        data_chunk(
            "tool-progress",
            {"toolCallId": call.tool_call_id, "status": "searching", "query": args.query},
            id=call.tool_call_id,
            transient=True,
        )
    )
    query = SearchQuery(
        query=args.query,
        max_results=args.max_results,
        topic=args.topic,
        recency=args.recency,
        include_domains=tuple(args.include_domains or ()),
    )
    with ctx.tracer.span("tavily.search", kind="retriever", input={"query": args.query, "topic": args.topic}) as span:
        results = await ctx.search.search(query)
        span.update(output={"results": len(results)})
    lines: list[str] = []
    outs: list[WebSearchResultOut] = []
    for result in results:
        source, is_new = ctx.sources.add(result.url, result.title)
        if is_new:
            call.write(source_url_chunk(str(source.id), result.url, result.title))
        lines.append(_format_result(source.id, result.title, result.url, result.snippet, result.published_at))
        outs.append(
            WebSearchResultOut(
                source_id=str(source.id),
                title=result.title,
                url=result.url,
                snippet=result.snippet,
                published_at=result.published_at,
                score=result.score,
            )
        )
    if lines:
        content = f'Search results for "{args.query}" ({len(lines)}). Cite as [n].\n\n' + "\n".join(lines)
    else:
        content = f'No results for "{args.query}". Try different wording or a broader query.'
    output: JsonObject = WebSearchOut(query=args.query, results=outs).model_dump(by_alias=True, mode="json")
    return ToolResult(content=content, output=output)


WEB_SEARCH: ToolSpec = Tool(
    name="web_search", description=DESCRIPTION, args_schema=WebSearchIn, requires="search", run=_run
)
