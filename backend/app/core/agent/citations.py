"""URL citations on a model's text, numbered through the run's sources.

OpenAI's built-in ``web_search`` cites inside the message: ``url_citation`` annotations on the text
blocks say which span a source supports — usually the inline markdown link the model wrote. This
module registers those sources in the run's :class:`SourceRegistry` (the same ``[n]`` space the
Tavily tools use, streamed once as ``source-url``) and appends `` [n]`` only to a cited span that
is not already a link, so the frontend's citation rendering works for both search engines. The
``web_search_call`` blocks themselves are ``server_tools.py``'s business.

Everything is pure: the stream mapper (``parts.py``) and the research subagent call in with the
run's registry and a chunk writer.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.tools.base import SourceRegistry
from app.core.ui_stream import UIChunk, source_url_chunk

type ChunkSink = Callable[[UIChunk], None]

_CITATION_TYPES = frozenset({"url_citation", "citation"})
# Punctuation a citation marker goes in front of, so "fast [1]." rather than "fast. [1]".
_TRAILING = ".,;:!?"
# An inline markdown link, optionally wrapped in parentheses the way OpenAI writes its citations.
_WRAPPED_LINK = re.compile(r"\(\[[^\]\n]*\]\((https?://[^)\s]+)\)\)")
_BARE_LINK = re.compile(r"\[[^\]\n]*\]\((https?://[^)\s]+)\)")


@dataclass(frozen=True, slots=True)
class UrlCitation:
    """One ``url_citation`` annotation: ``url`` supports ``text[start:end]``."""

    url: str
    title: str | None
    start: int
    end: int


def marker(source_id: int) -> str:
    return f"[{source_id}]"


def clean_url(url: str) -> str:
    """Drop ``utm_*`` tracking parameters (OpenAI appends ``utm_source=chatgpt.com`` to cited URLs)."""
    parts = urlsplit(url.strip())
    if not parts.query:
        return url.strip()
    kept = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if not key.startswith("utm_")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def blocks_of(content: object) -> list[Mapping[str, object]]:
    """A message's content as blocks (a plain string is one text block)."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return []
    blocks: list[Mapping[str, object]] = []
    for block in cast("list[object]", content):
        if isinstance(block, str):
            if block:
                blocks.append({"type": "text", "text": block})
        elif isinstance(block, Mapping):
            blocks.append(cast("Mapping[str, object]", block))
    return blocks


def citations_of(block: Mapping[str, object]) -> list[UrlCitation]:
    """The URL citations on one text block (raw ``url_citation`` or normalized ``citation`` shape)."""
    annotations = block.get("annotations")
    if not isinstance(annotations, list):
        return []
    citations: list[UrlCitation] = []
    for raw in cast("list[object]", annotations):
        if not isinstance(raw, Mapping):
            continue
        annotation = cast("Mapping[str, object]", raw)
        url = annotation.get("url")
        if annotation.get("type") not in _CITATION_TYPES or not isinstance(url, str) or not url:
            continue
        title = annotation.get("title")
        citations.append(
            UrlCitation(
                url=url,
                title=title if isinstance(title, str) and title else None,
                start=_index(annotation.get("start_index")),
                end=_index(annotation.get("end_index")),
            )
        )
    return citations


def citations_in(content: object) -> list[UrlCitation]:
    return [citation for block in blocks_of(content) for citation in citations_of(block)]


def span_links(span: str, url: str) -> bool:
    """Whether ``span`` already carries a markdown link to ``url``'s host — the model's own inline citation."""
    host = urlsplit(url.strip()).netloc.lower()
    return bool(host) and "](" in span and host in span.lower()


def cite_text(text: str, citations: Sequence[UrlCitation], sources: SourceRegistry, write: ChunkSink) -> str:
    """``text`` with every citation numbered: new sources go out as ``source-url``, and a cited span that
    is not already a link to its source gets `` [n]`` appended.

    OpenAI's cited spans are the inline markdown links the model writes, which the UI renders as
    citation pills — those need no marker. Markers are inserted from the back so earlier offsets
    stay valid, land before trailing punctuation, and are never repeated for one spot or one the
    text already carries.
    """
    # Number in reading order (the first citation is [1]), then insert from the back.
    ordered = sorted(citations, key=lambda item: (item.end, item.start))
    numbered = [(citation, register(sources, citation, write)) for citation in ordered]
    result = text
    inserted: set[tuple[int, int]] = set()
    for citation, source_id in reversed(numbered):
        end = min(max(citation.end, 0), len(text))
        if (end, source_id) in inserted or span_links(text[citation.start : end], citation.url):
            continue
        inserted.add((end, source_id))
        at = end - 1 if 0 < end <= len(result) and result[end - 1] in _TRAILING else end
        if result[:at].rstrip().endswith(marker(source_id)):
            continue
        result = f"{result[:at]} {marker(source_id)}{result[at:]}"
    return result


def cite_content(content: object, sources: SourceRegistry, write: ChunkSink) -> str:
    """The text of a landed message with its citations marked (one text block at a time)."""
    return "".join(
        cite_text(str(block.get("text", "")), citations_of(block), sources, write)
        for block in blocks_of(content)
        if block.get("type") == "text"
    )


def number_links(text: str, sources: SourceRegistry) -> str:
    """Inline links to numbered sources become their ``[n]`` — research findings are cited that way
    in the synthesis prompt, whichever search engine the subagent used. Other links stay."""

    def swap(match: re.Match[str]) -> str:
        source = sources.find(clean_url(match.group(1)))
        return marker(source.id) if source is not None else match.group(0)

    return _BARE_LINK.sub(swap, _WRAPPED_LINK.sub(swap, text))


def register(sources: SourceRegistry, citation: UrlCitation, write: ChunkSink) -> int:
    """Number a cited URL (deduped, tracking parameters dropped); a new one is streamed once."""
    source, is_new = sources.add(clean_url(citation.url), citation.title)
    if is_new:
        write(source_url_chunk(str(source.id), source.url, source.title))
    return source.id


# ── Helpers ──────────────────────────────────────────────────────────────────


def _index(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0
