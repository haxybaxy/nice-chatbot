"""The tracer seam: the no-op contract, deterministic trace ids, and the Langfuse tracer's control flow."""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from uuid import UUID, uuid4

from app.core.observability import LangfuseTracer, NoopTracer, SpanKind, Tracer, default_tracer, trace_id_for_run

HEX_32 = re.compile(r"^[0-9a-f]{32}$")
KINDS: tuple[SpanKind, ...] = ("span", "tool", "retriever")


def _run(tracer: Tracer, run_id: UUID, *, mode: str = "chat", attempt: int = 1) -> AbstractContextManager[str | None]:
    return tracer.run_context(
        run_id=run_id,
        conversation_id=uuid4(),
        user_id=uuid4(),
        team_id=uuid4(),
        mode=mode,
        model="anthropic:claude-opus-5-5",
        attempt=attempt,
        tags=("extra",),
    )


class TestTraceId:
    def test_deterministic_32_hex(self) -> None:
        run_id = uuid4()
        first = trace_id_for_run(run_id)
        assert HEX_32.match(first)
        assert trace_id_for_run(run_id) == first
        assert trace_id_for_run(uuid4()) != first
        assert trace_id_for_run(UUID(int=1)) == trace_id_for_run(UUID(int=1))


class TestNoop:
    def test_contract(self) -> None:
        tracer = NoopTracer()
        assert tracer.callbacks() == []
        with _run(tracer, uuid4()) as trace_id:
            assert trace_id is None
            with tracer.span("tavily.search", kind="retriever", input={"q": 1}) as span:
                span.update(output={"n": 2}, level="WARNING", status_message="x")
        tracer.flush()
        tracer.shutdown()

    def test_default_tracer_is_noop_without_keys(self) -> None:
        assert isinstance(default_tracer(), NoopTracer)
        assert default_tracer() is default_tracer()


class TestLangfuse:
    def test_control_flow_with_tracing_disabled(self) -> None:
        tracer = LangfuseTracer(
            public_key="pk-test",
            secret_key="sk-test",
            base_url="http://127.0.0.1:9",
            environment="test",
            release="0.0.0",
            tracing_enabled=False,
        )
        run_id = uuid4()
        with _run(tracer, run_id, mode="deep_research", attempt=2) as trace_id:
            assert trace_id == trace_id_for_run(run_id)
            handlers = tracer.callbacks()
            assert len(handlers) == 1
            for kind in KINDS:
                with tracer.span(f"test.{kind}", kind=kind, input={"k": kind}) as span:
                    span.update(output={"ok": True})
        tracer.flush()
        tracer.shutdown()
        tracer.shutdown()  # idempotent
