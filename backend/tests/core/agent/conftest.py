"""Fixtures for the agent graph tests: a scripted ``echo`` tool and the shared harness."""

from __future__ import annotations

import asyncio
from typing import Literal

import pytest
from langchain_core.tools import BaseTool
from pydantic import Field

from app.core.exceptions import AppError
from app.core.schemas import BaseSchema
from app.core.tools.base import RunContext, Tool, ToolCallContext, ToolResult, ToolSpec
from app.core.tools.registry import ToolRegistry
from app.core.ui_stream import data_chunk
from tests.fakes_llm import OPUS, make_run_context
from tests.graph_harness import chat_graph, collect, prompt, scripted_model

__all__ = ["ECHO", "chat_graph", "collect", "echo_tools", "prompt", "scripted_model"]


class EchoIn(BaseSchema):
    text: str = Field(max_length=200)
    fail: Literal["none", "app", "bug", "hang"] = "none"


async def _echo(call: ToolCallContext, args: EchoIn) -> ToolResult:
    if args.fail == "app":
        raise AppError.service_unavailable("echo service down")
    if args.fail == "bug":
        raise RuntimeError("echo exploded")
    if args.fail == "hang":
        await asyncio.sleep(30)
    call.write(
        data_chunk(
            "tool-progress",
            {"toolCallId": call.tool_call_id, "status": "echoing"},
            id=call.tool_call_id,
            transient=True,
        )
    )
    return ToolResult(content=f"echo: {args.text}", output={"text": args.text})


ECHO: ToolSpec = Tool(name="echo", description="Repeats text.", args_schema=EchoIn, requires=None, run=_echo)


def echo_tools(ctx: RunContext) -> list[BaseTool]:
    return ToolRegistry([ECHO]).for_run(ctx, names={"echo"}, spec=OPUS)


@pytest.fixture
def ctx() -> RunContext:
    return make_run_context()
