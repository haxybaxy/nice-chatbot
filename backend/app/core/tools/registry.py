"""Per-run tools from the built-in :class:`ToolSpec`s, and the graph's ``ToolNode``.

``ToolRegistry.for_run`` resolves the names a run asked for into a :class:`RunTools`: the
closure-based ``StructuredTool``s the graph runs itself (the model sees the tool's JSON schema; the
closure checks cancel and budget, re-validates the arguments with the tool's ``BaseSchema``, runs it
with the run's :class:`RunContext`, caps the text the model reads and returns ``(content,
artifact)`` so the UI gets the structured output), the provider-executed tools bound next to them
(OpenAI's built-in ``web_search`` when the model has it — it then covers ``web_fetch`` too), and the
honest bookkeeping the prompt reads: which names are bound and which were requested but cannot be
offered here (no search client, no sandbox, a model without tool support). Client tools are sorted
by name so the rendered tool block — the first bytes of every request — is byte-identical across
turns (prompt caching).

Failures never fail the run: ``build_tool_node`` installs ``handle_tool_errors`` so invalid
arguments, provider ``AppError``s and bugs all become an error ``ToolMessage`` the model can
recover from.
"""

# Library boundary: StructuredTool.from_function, ToolNode and ToolRuntime are typed with `Any`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from functools import cache

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt import ToolNode, ToolRuntime
from langgraph.prebuilt.tool_node import ToolInvocationError
from pydantic import ValidationError

from app.core.exceptions import AppError
from app.core.llm.catalog import ModelSpec
from app.core.llm.chat_models import ProviderTool
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
# OpenAI's server-side web search (Responses API). Bound under the same wire name as the Tavily
# tool, so the UI renders both as `tool-web_search`.
NATIVE_WEB_SEARCH: ProviderTool = {"type": "web_search"}
WEB_SEARCH_NAME = WEB_SEARCH.name


@dataclass(frozen=True, slots=True)
class RunTools:
    """The tools of one run: what the graph runs, what the provider runs, and the honest names."""

    # LangChain tools the graph's ``ToolNode`` executes.
    client: tuple[BaseTool, ...] = ()
    # Provider-executed tools, bound next to them (their calls come back inside the model's message).
    provider: tuple[ProviderTool, ...] = ()
    # The wire names actually bound, sorted — what the system prompt lists as enabled.
    names: tuple[str, ...] = ()
    # Requested names this server cannot offer, sorted — what the prompt lists as unavailable.
    unavailable: tuple[str, ...] = ()
    # ``web_search`` is the provider's built-in search (citations arrive with the text).
    native_web_search: bool = False

    @property
    def bound(self) -> list[BaseTool | ProviderTool]:
        return [*self.client, *self.provider]

    def __bool__(self) -> bool:
        return bool(self.client or self.provider)


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

    def configured(self, *, search: bool, sandbox: bool, native_web_search: bool) -> list[str]:
        """The tool names this server can offer at all (the worker's start log)."""
        names: list[str] = []
        for name, tool in self._specs.items():
            backed = (
                tool.requires is None
                or (tool.requires == "search" and search)
                or (tool.requires == "sandbox" and sandbox)
            )
            if backed or (name == WEB_SEARCH_NAME and native_web_search):
                names.append(name)
        return sorted(names)

    def for_run(self, ctx: RunContext, *, names: Collection[str], spec: ModelSpec) -> RunTools:
        """Resolve the requested names for one run on ``spec``.

        ``web_search`` becomes the provider's built-in search when the model has one (``web_fetch``
        is then covered by it), else the Tavily tools when a search client exists; ``run_code`` needs
        the sandbox. Whatever cannot be offered is reported in ``unavailable`` rather than dropped
        silently, so the prompt never promises a tool the model does not have.
        """
        requested = [name for name in sorted(set(names)) if name in self._specs or self._warn_unknown(name)]
        if not spec.supports_tools:
            return RunTools(unavailable=tuple(requested))
        native = spec.native_web_search and WEB_SEARCH_NAME in requested
        client: list[BaseTool] = []
        provider: list[ProviderTool] = []
        bound: list[str] = []
        unavailable: list[str] = []
        for name in requested:
            tool = self._specs[name]
            if native and name == WEB_SEARCH_NAME:
                provider.append(dict(NATIVE_WEB_SEARCH))
                bound.append(name)
            elif native and tool.requires == "search":
                continue  # the built-in search reads pages itself
            elif (tool.requires == "search" and ctx.search is None) or (
                tool.requires == "sandbox" and ctx.sandbox is None
            ):
                unavailable.append(name)
            else:
                client.append(_structured_tool(tool, ctx))
                bound.append(name)
        return RunTools(
            client=tuple(client),
            provider=tuple(provider),
            names=tuple(sorted(bound)),
            unavailable=tuple(sorted(unavailable)),
            native_web_search=native,
        )

    @staticmethod
    def _warn_unknown(name: str) -> bool:
        logger.warning("unknown tool requested", tool=name)
        return False


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
