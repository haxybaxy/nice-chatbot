"""Argument and output schemas of the built-in tools.

Inputs are ``BaseSchema`` (the model's arguments are re-validated here before a tool runs; the
model-facing JSON schema is derived from them with snake_case names). Outputs are
``BaseSchemaOut`` and are dumped by alias, so the ``tool-output-available`` payload the UI
renders is camelCase like every other wire object. Text the tools return (page content, program
output) is ``VerbatimStr``: the bases strip surrounding whitespace, which would corrupt it.
"""

from typing import Literal

from pydantic import Field

from app.core.schemas import BaseSchema, BaseSchemaOut, VerbatimStr

# ── web_search ───────────────────────────────────────────────────────────────


class WebSearchIn(BaseSchema):
    query: str = Field(max_length=400, description="What to search for; a focused natural-language query.")
    max_results: int = Field(default=5, ge=1, le=10, description="How many results to return (1 to 10).")
    topic: Literal["general", "news", "finance"] = Field(
        default="general", description="Search vertical: general web, recent news, or finance."
    )
    recency: Literal["day", "week", "month", "year"] | None = Field(
        default=None, description="Only results published within this window; null for no limit."
    )
    include_domains: list[str] | None = Field(
        default=None, max_length=10, description="Restrict results to these domains (at most 10); null for any."
    )


class WebSearchResultOut(BaseSchemaOut):
    source_id: str
    title: str
    url: str
    snippet: VerbatimStr
    published_at: str | None = None
    score: float | None = None


class WebSearchOut(BaseSchemaOut):
    query: str
    results: list[WebSearchResultOut]


# ── web_fetch ────────────────────────────────────────────────────────────────


class WebFetchIn(BaseSchema):
    url: str = Field(max_length=2048, description="The http(s) page to read.")
    max_chars: int = Field(default=8000, ge=500, le=20000, description="Cap on the returned text (500 to 20000).")
    query: str | None = Field(
        default=None, max_length=400, description="What you are looking for on the page; focuses the extract."
    )


class WebFetchOut(BaseSchemaOut):
    source_id: str
    url: str
    title: str | None = None
    content: VerbatimStr
    chars: int
    truncated: bool


# ── run_code ─────────────────────────────────────────────────────────────────


class RunCodeIn(BaseSchema):
    language: Literal["python", "bash"] = Field(description="Interpreter: python (3.13) or bash.")
    code: str = Field(max_length=20000, description="The program; read from stdin, so print what you need to see.")
    timeout_s: int = Field(
        default=0, ge=0, le=120, description="Wall-clock limit in seconds (1 to 120); 0 for the server default."
    )


class RunCodeOut(BaseSchemaOut):
    stdout: VerbatimStr
    stderr: VerbatimStr
    exit_code: int
    duration_ms: int
    truncated: bool
    timed_out: bool
