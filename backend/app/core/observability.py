"""Tracing seam — Langfuse behind a Protocol, a no-op when no keys are configured.

The worker opens one ``run_context`` per assistant turn: a root ``agent`` observation whose trace
id is ``trace_id_for_run(run.id)`` (deterministic, so the API can store it on the run row before
the worker ever starts), with the conversation as the Langfuse session and the user, team, mode
and model propagated to every nested observation. ``callbacks()`` builds the LangChain handler
inside that context, so every LangGraph node, model call and tool call nests under the root span;
``span()`` wraps the Tavily and sandbox calls the tools make.

Only this module imports ``langfuse`` (ruff ``TID251``). Tests use ``NoopTracer`` or the
``FakeTracer`` in ``tests/fakes_llm.py``.
"""

# Library boundary: the Langfuse SDK types its observation wrappers and `propagate_attributes` with `Any`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import AbstractContextManager, contextmanager
from functools import cache
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import Depends
from langchain_core.callbacks import BaseCallbackHandler
from langfuse import Langfuse, propagate_attributes  # noqa: TID251
from langfuse.langchain import CallbackHandler  # noqa: TID251

from app.core.config import langfuse_settings, settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

type SpanKind = Literal["span", "tool", "retriever"]
type SpanLevel = Literal["DEBUG", "DEFAULT", "WARNING", "ERROR"]


class SpanHandle(Protocol):
    """What a tool may record on its span once the call has finished."""

    def update(
        self, *, output: object = None, level: SpanLevel | None = None, status_message: str | None = None
    ) -> None: ...


class Tracer(Protocol):
    def callbacks(self) -> list[BaseCallbackHandler]:
        """LangChain callbacks for one graph run; call inside ``run_context``."""
        ...

    def run_context(
        self,
        *,
        run_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
        team_id: UUID,
        mode: str,
        model: str,
        attempt: int,
        tags: Sequence[str] = (),
    ) -> AbstractContextManager[str | None]:
        """The root observation of one run; yields its trace id (``None`` when tracing is off)."""
        ...

    def span(
        self, name: str, *, kind: SpanKind = "span", input: object = None
    ) -> AbstractContextManager[SpanHandle]: ...

    def flush(self) -> None:
        """Push buffered observations; called after every run."""
        ...

    def shutdown(self) -> None:
        """Flush and release the exporter; called once at process exit."""
        ...


def trace_id_for_run(run_id: UUID) -> str:
    """The Langfuse trace id of a run: 32 hex characters derived from the run id, no network."""
    return Langfuse.create_trace_id(seed=str(run_id))


# ── No-op ────────────────────────────────────────────────────────────────────


class NoopSpanHandle:
    def update(
        self, *, output: object = None, level: SpanLevel | None = None, status_message: str | None = None
    ) -> None:
        del output, level, status_message


class NoopTracer:
    """Satisfies :class:`Tracer` without recording anything (no Langfuse keys, or tracing disabled)."""

    def callbacks(self) -> list[BaseCallbackHandler]:
        return []

    @contextmanager
    def run_context(
        self,
        *,
        run_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
        team_id: UUID,
        mode: str,
        model: str,
        attempt: int,
        tags: Sequence[str] = (),
    ) -> Generator[str | None]:
        del run_id, conversation_id, user_id, team_id, mode, model, attempt, tags
        yield None

    @contextmanager
    def span(self, name: str, *, kind: SpanKind = "span", input: object = None) -> Generator[SpanHandle]:
        del name, kind, input
        yield NoopSpanHandle()

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


# ── Langfuse ─────────────────────────────────────────────────────────────────


class _LangfuseSpanHandle:
    def __init__(self, observation: object) -> None:
        self._observation = observation

    def update(
        self, *, output: object = None, level: SpanLevel | None = None, status_message: str | None = None
    ) -> None:
        update = getattr(self._observation, "update", None)
        if callable(update):
            update(output=output, level=level, status_message=status_message)


class LangfuseTracer:
    """:class:`Tracer` over the Langfuse v5 SDK (OpenTelemetry under the hood).

    The client is built on first use so importing this module never opens a connection.
    ``tracing_enabled=False`` keeps the whole control flow but exports nothing (tests).
    """

    def __init__(
        self,
        *,
        public_key: str,
        secret_key: str,
        base_url: str,
        environment: str,
        release: str,
        tracing_enabled: bool = True,
    ) -> None:
        self._public_key = public_key
        self._secret_key = secret_key
        self._base_url = base_url
        self._environment = environment
        self._release = release
        self._tracing_enabled = tracing_enabled
        self._client: Langfuse | None = None

    def _langfuse(self) -> Langfuse:
        if self._client is None:
            self._client = Langfuse(
                public_key=self._public_key,
                secret_key=self._secret_key,
                base_url=self._base_url,
                environment=self._environment,
                release=self._release,
                tracing_enabled=self._tracing_enabled,
            )
        return self._client

    def callbacks(self) -> list[BaseCallbackHandler]:
        # Built inside run_context: the handler parents its observations on the current span.
        self._langfuse()
        return [CallbackHandler(public_key=self._public_key)]

    @contextmanager
    def run_context(
        self,
        *,
        run_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
        team_id: UUID,
        mode: str,
        model: str,
        attempt: int,
        tags: Sequence[str] = (),
    ) -> Generator[str | None]:
        trace_id = trace_id_for_run(run_id)
        name = f"chat.{mode}"
        client = self._langfuse()
        with (
            client.start_as_current_observation(
                as_type="agent",
                name=name,
                trace_context={"trace_id": trace_id},
                metadata={"run_id": str(run_id), "attempt": attempt},
            ),
            propagate_attributes(
                user_id=str(user_id),
                session_id=str(conversation_id),
                trace_name=name,
                tags=[f"team:{team_id}", f"mode:{mode}", f"model:{model}", *tags],
                metadata={"run_id": str(run_id), "attempt": str(attempt)},
            ),
        ):
            yield trace_id

    @contextmanager
    def span(self, name: str, *, kind: SpanKind = "span", input: object = None) -> Generator[SpanHandle]:
        client = self._langfuse()
        # One branch per literal: the SDK overloads `start_as_current_observation` on `as_type`.
        if kind == "tool":
            manager = client.start_as_current_observation(as_type="tool", name=name, input=input)
        elif kind == "retriever":
            manager = client.start_as_current_observation(as_type="retriever", name=name, input=input)
        else:
            manager = client.start_as_current_observation(as_type="span", name=name, input=input)
        with manager as observation:
            yield _LangfuseSpanHandle(observation)

    def flush(self) -> None:
        if self._client is not None:
            self._client.flush()

    def shutdown(self) -> None:
        if self._client is not None:
            self._client.shutdown()
            self._client = None


# ── Wiring ───────────────────────────────────────────────────────────────────


@cache
def default_tracer() -> Tracer:
    """The process tracer: Langfuse when both keys are set and enabled, otherwise a no-op."""
    if not langfuse_settings.configured:
        logger.info("tracing disabled", reason="langfuse keys not configured or LANGFUSE_ENABLED=false")
        return NoopTracer()
    secret = langfuse_settings.langfuse_secret_key
    public = langfuse_settings.langfuse_public_key
    if secret is None or public is None:  # pragma: no cover — `configured` already checked both
        return NoopTracer()
    logger.info("tracing enabled", base_url=langfuse_settings.langfuse_base_url)
    return LangfuseTracer(
        public_key=public,
        secret_key=secret.get_secret_value(),
        base_url=langfuse_settings.langfuse_base_url,
        environment=settings.environment,
        release=settings.version,
    )


async def get_tracer() -> Tracer:
    return default_tracer()


TracerDep = Annotated[Tracer, Depends(get_tracer)]
