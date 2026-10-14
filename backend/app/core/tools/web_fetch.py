"""``web_fetch`` — read one public http(s) page through ``SearchClient.extract``; the page is a source ``[n]``."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from app.core.exceptions import AppError
from app.core.tools.base import Tool, ToolCallContext, ToolInputError, ToolResult, ToolSpec
from app.core.tools.schemas import WebFetchIn, WebFetchOut
from app.core.ui_stream import JsonObject, data_chunk, source_url_chunk

DESCRIPTION = (
    "Read a web page and return its main text as markdown. Use it to read a web_search result in "
    "full, to open a URL the user gave you, or to check documentation. Public http(s) pages only. "
    "The page becomes a numbered source: cite it as [n]."
)
_BLOCKED_HOSTS = frozenset({"localhost", "localhost.localdomain", "metadata.google.internal"})
_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost")


def validate_fetch_url(url: str) -> str:
    """Only public http(s) hosts: no IP literals, loopback names or internal-looking suffixes."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise ToolInputError("url must be an http(s) URL")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ToolInputError("url must use a host name, not an IP address")
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES) or "." not in host:
        raise ToolInputError("url must point at a public host")
    return url.strip()


async def _run(call: ToolCallContext, args: WebFetchIn) -> ToolResult:
    ctx = call.ctx
    url = validate_fetch_url(args.url)
    if ctx.search is None:
        raise AppError.service_unavailable("Web fetch is not configured")
    call.write(
        data_chunk(
            "tool-progress",
            {"toolCallId": call.tool_call_id, "status": "fetching", "url": url},
            id=call.tool_call_id,
            transient=True,
        )
    )
    with ctx.tracer.span("tavily.extract", kind="retriever", input={"url": url}) as span:
        pages, failed = await ctx.search.extract([url], query=args.query, depth="basic")
        span.update(output={"pages": len(pages), "failed": len(failed)})
    page = next((item for item in pages if item.content), None)
    if page is None:
        raise AppError.bad_request("The page could not be fetched or has no readable text", url=url)
    source, is_new = ctx.sources.add(page.url or url, page.title)
    if is_new:
        call.write(source_url_chunk(str(source.id), source.url, source.title))
    text = page.content.strip()
    truncated = len(text) > args.max_chars
    if truncated:
        text = text[: args.max_chars].rstrip()
    heading = f"[{source.id}] {page.title or source.url} — {source.url}"
    content = f"{heading}\n\n{text}" + ("\n\n[truncated — ask for a later section with a query]" if truncated else "")
    output: JsonObject = WebFetchOut(
        source_id=str(source.id), url=source.url, title=page.title, content=text, chars=len(text), truncated=truncated
    ).model_dump(by_alias=True, mode="json")
    return ToolResult(content=content, output=output)


WEB_FETCH: ToolSpec = Tool(
    name="web_fetch", description=DESCRIPTION, args_schema=WebFetchIn, requires="search", run=_run
)
