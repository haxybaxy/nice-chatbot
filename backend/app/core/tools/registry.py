"""Per-run LangChain tools from the built-in :class:`ToolSpec`s, and the graph's ``ToolNode``.

``ToolRegistry.for_run`` builds one closure-based ``StructuredTool`` per requested tool: the model
sees the tool's JSON schema; the closure checks cancel and budget, re-validates the arguments
with the tool's ``BaseSchema``, runs it with the run's :class:`RunContext`, caps the text the
model reads and returns ``(content, artifact)`` so the UI gets the structured output. Tools whose
capability is missing (no search client, no sandbox) or that the model cannot call are left out,
and the list is sorted by name so the rendered tool block — the first bytes of every request —
is byte-identical across turns (prompt caching).

Failures never fail the run: ``build_tool_node`` installs ``handle_tool_errors`` so invalid
arguments, provider ``AppError``s and bugs all become an error ``ToolMessage`` the model can
recover from.
"""

# Library boundary: StructuredTool.from_function, ToolNode and ToolRuntime are typed with `Any`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from collections.abc import Collection, Sequence
from functools import cache

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt import ToolNode, ToolRuntime
from langgraph.prebuilt.tool_node import ToolInvocationError
from pydantic import ValidationError

from app.core.exceptions import AppError
from app.core.llm.catalog import ModelSpec
from app.core.logging_config import get_logger
from app.core.tools.base import RunContext, ToolArtifact, ToolCallContext, ToolInputError, ToolSpec
from app.core.tools.run_code import RUN_CODE
from app.core.tools.web_fetch import WEB_FETCH
from app.core.tools.web_search import WEB_SEARCH
from app.core.ui_stream import JsonObject

logger = get_logger(__name__)

BUDGET_EXHAUSTED = "Tool budget exhausted — answer with what you have."
RUN_CANCELLED = "The run was cancelled; do not call more tools."
UNEXPECTED_FAILURE = "The tool failed unexpectedly. Continue without it."
_TRUNCATION_NOTE = "\n\n[output truncated]"


def _describe(error: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors())


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(_TRUNCATION_NOTE))].rstrip() + _TRUNCATION_NOTE


def _structured_tool(spec: ToolSpec, ctx: RunContext) -> StructuredTool:
    async def _invoke(runtime: ToolRuntime[RunContext, object], **arguments: object) -> tuple[str, ToolArtifact]:
        if ctx.cancel.requested:
            return RUN_CANCELLED, {"output": {"error": "cancelled"}, "is_error": True}
        if not ctx.budget.take():
            return BUDGET_EXHAUSTED, {"output": {"error": "tool_budget_exhausted"}, "is_error": True}
        call = ToolCallContext(ctx=ctx, tool_call_id=runtime.tool_call_id or "", write=runtime.stream_writer)
        try:
            result = await spec.invoke(call, arguments)
        except ValidationError as error:
            raise ToolInputError(f"Invalid arguments for {spec.name}: {_describe(error)}") from error
        content = _truncate(result.content, ctx.budget.max_output_chars)
        return content, {"output": result.output, "is_error": result.is_error}

    schema: JsonObject = spec.json_schema()
    return StructuredTool.from_function(
        coroutine=_invoke,
        name=spec.name,
        description=spec.description,
        args_schema=schema,
        response_format="content_and_artifact",
        extras={"eager_input_streaming": True},
    )


class ToolRegistry:
    """The built-in tools, keyed by their wire name (``web_search``, ``web_fetch``, ``run_code``)."""

    def __init__(self, specs: Sequence[ToolSpec]) -> None:
        self._specs: dict[str, ToolSpec] = {spec.name: spec for spec in specs}

    def names(self) -> list[str]:
        return sorted(self._specs)

    def for_run(self, ctx: RunContext, *, names: Collection[str], spec: ModelSpec) -> list[BaseTool]:
        """The LangChain tools for one run: requested ∩ known ∩ backed by a configured client, sorted by name."""
        if not spec.supports_tools:
            return []
        tools: list[BaseTool] = []
        for name in sorted(set(names)):
            tool = self._specs.get(name)
            if tool is None:
                logger.warning("unknown tool requested", tool=name)
                continue
            if tool.requires == "search" and ctx.search is None:
                continue
            if tool.requires == "sandbox" and ctx.sandbox is None:
                continue
            tools.append(_structured_tool(tool, ctx))
        return tools


def tool_error_text(error: Exception) -> str:
    """What the model reads when a tool call fails; the run goes on."""
    if isinstance(error, ToolInputError | ToolInvocationError):
        return str(error)
    if isinstance(error, AppError):
        return f"Tool failed: {error.message}"
    logger.error("tool crashed", error=repr(error))
    return UNEXPECTED_FAILURE


def build_tool_node(tools: Sequence[BaseTool]) -> ToolNode:
    """The graph node that runs a step's tool calls in parallel and lands them in one state update."""
    return ToolNode(list(tools), handle_tool_errors=tool_error_text)


@cache
def default_tool_registry() -> ToolRegistry:
    return ToolRegistry([WEB_SEARCH, WEB_FETCH, RUN_CODE])
