"""``run_code``: the sandbox result as the model and the UI see it; non-zero exit is not an error."""

from __future__ import annotations

from typing import cast

from app.core.exceptions import AppError
from app.core.sandbox import SandboxResult
from tests.fakes_llm import FakeSandboxClient, FakeTracer, make_run_context, scripted_turn
from tests.graph_harness import chat_graph, collect, prompt, scripted_model, tools_for


async def test_run_code_reports_stdout_stderr_and_exit_code() -> None:
    sandbox = FakeSandboxClient(
        results=[
            SandboxResult(stdout="391\n", stderr="", exit_code=0, duration_ms=120, truncated=False, timed_out=False)
        ]
    )
    tracer = FakeTracer()
    ctx = make_run_context(sandbox=sandbox, tracer=tracer)
    turn = scripted_turn(tool_calls=[("run_code", {"language": "python", "code": "print(17*23)"})])
    model, built = scripted_model([turn, scripted_turn("17 x 23 = 391.")])
    result = await collect(chat_graph(built, tools_for(ctx, {"run_code"})), ctx, prompt())

    assert sandbox.runs[0].language == "python"
    assert sandbox.runs[0].code == "print(17*23)"
    assert sandbox.runs[0].timeout_s == 30
    content = str(model.calls[1][-1].content)
    assert content == "exit code 0 in 120 ms\n\nstdout:\n391\n\nstderr: (empty)"
    assert result.first("tool-output-available")["output"] == {
        "stdout": "391\n",
        "stderr": "",
        "exitCode": 0,
        "durationMs": 120,
        "truncated": False,
        "timedOut": False,
    }
    assert result.first("data-tool-progress")["data"] == {
        "toolCallId": turn.tool_calls[0]["id"],
        "status": "running",
        "language": "python",
    }
    assert [span.name for span in tracer.spans] == ["sandbox.run"]
    assert tracer.spans[0].kind == "tool"
    assert tracer.spans[0].input == {"language": "python", "timeout_s": 30}


async def test_non_zero_exit_and_timeout_are_results_not_errors() -> None:
    sandbox = FakeSandboxClient(
        results=[
            SandboxResult(
                stdout="partial", stderr="Traceback...", exit_code=124, duration_ms=5000, truncated=True, timed_out=True
            )
        ]
    )
    ctx = make_run_context(sandbox=sandbox)
    turn = scripted_turn(tool_calls=[("run_code", {"language": "bash", "code": "sleep 99", "timeout_s": 5})])
    model, built = scripted_model([turn, scripted_turn("it hung")])
    result = await collect(chat_graph(built, tools_for(ctx, {"run_code"})), ctx, prompt())
    content = str(model.calls[1][-1].content)
    assert content.startswith("exit code 124 in 5000 ms (timed out after 5s) (output truncated)")
    assert "stderr:\nTraceback..." in content
    assert result.of_type("tool-output-error") == []
    output = cast("dict[str, object]", result.first("tool-output-available")["output"])
    assert output["timedOut"] is True


async def test_sandbox_unavailable_is_a_tool_failure() -> None:
    sandbox = FakeSandboxClient(error=AppError.service_unavailable("Code execution environment unavailable"))
    ctx = make_run_context(sandbox=sandbox)
    _, built = scripted_model(
        [scripted_turn(tool_calls=[("run_code", {"language": "python", "code": "1"})]), scripted_turn("no")]
    )
    result = await collect(chat_graph(built, tools_for(ctx, {"run_code"})), ctx, prompt())
    assert result.first("tool-output-error")["errorText"] == "Tool failed: Code execution environment unavailable"
