"""``run_code`` — execute Python or bash in the sandbox; a non-zero exit is a result, not an error."""

from __future__ import annotations

from app.core.config import sandbox_settings
from app.core.exceptions import AppError
from app.core.sandbox import SandboxRun
from app.core.tools.base import Tool, ToolCallContext, ToolResult, ToolSpec
from app.core.tools.schemas import RunCodeIn, RunCodeOut
from app.core.ui_stream import JsonObject, data_chunk

DESCRIPTION = (
    "Run a program in an isolated sandbox and return its stdout, stderr and exit code. Use it for "
    "arithmetic and data crunching, to verify code before you present it, or to transform text. "
    "Python 3.13 standard library or bash; no network, no package installs, no files persist "
    "between calls, 512 MB memory. Print what you want to see; nothing else is returned."
)


def _section(label: str, text: str) -> str:
    return f"{label}:\n{text.rstrip()}" if text.strip() else f"{label}: (empty)"


async def _run(call: ToolCallContext, args: RunCodeIn) -> ToolResult:
    ctx = call.ctx
    if ctx.sandbox is None:
        raise AppError.service_unavailable("Code execution is not available")
    timeout_s = args.timeout_s or sandbox_settings.sandbox_timeout_s
    call.write(
        data_chunk(
            "tool-progress",
            {"toolCallId": call.tool_call_id, "status": "running", "language": args.language},
            id=call.tool_call_id,
            transient=True,
        )
    )
    with ctx.tracer.span("sandbox.run", kind="tool", input={"language": args.language, "timeout_s": timeout_s}) as span:
        result = await ctx.sandbox.run(
            SandboxRun(language=args.language, code=args.code, timeout_s=timeout_s), cancel=ctx.cancel
        )
        span.update(
            output={"exit_code": result.exit_code, "duration_ms": result.duration_ms, "timed_out": result.timed_out}
        )
    status = f"exit code {result.exit_code} in {result.duration_ms} ms"
    if result.timed_out:
        status += f" (timed out after {timeout_s}s)"
    if result.truncated:
        status += " (output truncated)"
    content = "\n\n".join([status, _section("stdout", result.stdout), _section("stderr", result.stderr)])
    output: JsonObject = RunCodeOut(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        truncated=result.truncated,
        timed_out=result.timed_out,
    ).model_dump(by_alias=True, mode="json")
    return ToolResult(content=content, output=output)


RUN_CODE: ToolSpec = Tool(name="run_code", description=DESCRIPTION, args_schema=RunCodeIn, requires="sandbox", run=_run)
