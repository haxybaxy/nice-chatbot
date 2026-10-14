"""ORM models for the chat domain: conversations, their messages, and the runs that produce
assistant turns together with their event log.

JSONB columns (``parts``, ``provider_messages``, ``options``, ``payload``) are plain dicts and
lists: **reassign** a new value, never mutate in place — SQLAlchemy only sees the reassignment.
Enum-like columns are plain strings with a CHECK (adding a value is a code change plus a
migration of the constraint), the pattern ``organization_member.role`` set.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ui_stream import JsonObject
from app.db.base import Base, TimestampMixin


class ConversationVisibility(StrEnum):
    TEAM = "team"  # every team member can read it
    PRIVATE = "private"  # only its creator


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunMode(StrEnum):
    CHAT = "chat"
    DEEP_RESEARCH = "deep_research"


ACTIVE_RUN_STATUSES: tuple[str, ...] = (RunStatus.QUEUED.value, RunStatus.RUNNING.value)
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset(
    {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}
)
# The partial unique index `uq_run_active_conversation` keeps one active run per conversation.
# The migration carries this exact text; keep them identical.
ACTIVE_RUN_PREDICATE = "status IN ('queued', 'running')"


class ConversationModel(Base, TimestampMixin):
    __tablename__ = "conversation"
    __table_args__ = (
        CheckConstraint("visibility IN ('team', 'private')", name="visibility"),
        # The team's conversation list: newest activity first.
        Index(None, "team_id", "last_message_at"),
    )

    team_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("team.id", ondelete="CASCADE"))
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"))
    title: Mapped[str | None] = mapped_column(String(255))
    visibility: Mapped[str] = mapped_column(String(20), default=ConversationVisibility.TEAM.value)
    # The model of the latest run — what the picker shows when the conversation is reopened.
    model: Mapped[str | None] = mapped_column(String(100))
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # The queued or running run, if any (at most one: `uq_run_active_conversation`). Read-only;
    # `refresh(conversation, ["active_run"])` after creating or finishing a run.
    active_run: Mapped["RunModel | None"] = relationship(
        primaryjoin="and_(RunModel.conversation_id == ConversationModel.id, RunModel.status.in_(['queued', 'running']))",
        viewonly=True,
        lazy="selectin",
        uselist=False,
    )


class RunModel(Base, TimestampMixin):
    """One assistant turn: queued by ``POST .../messages``, claimed and driven by a worker."""

    __tablename__ = "run"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name="status"),
        CheckConstraint("mode IN ('chat', 'deep_research')", name="mode"),
        # The worker's claim query (queued runs, oldest first) and the reaper (running runs).
        Index(None, "status", "created_at"),
        Index(
            "uq_run_active_conversation", "conversation_id", unique=True, postgresql_where=text(ACTIVE_RUN_PREDICATE)
        ),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE"), index=True
    )
    requested_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.QUEUED.value)
    mode: Mapped[str] = mapped_column(String(20), default=RunMode.CHAT.value)
    # "<provider>:<model-id>" as in the catalog, plus the provider alone for cheap filtering.
    model: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(20))
    effort: Mapped[str] = mapped_column(String(10))
    # Tool switches of the run: web_search (search + fetch) and code, both booleans.
    options: Mapped[JsonObject] = mapped_column(JSONB)
    # User-safe failure text, set with status=failed.
    error: Mapped[str | None] = mapped_column(Text)
    # Lease: the worker that claimed the run and its heartbeat. Every worker write is fenced by
    # `worker_id = :me AND status = 'running'`.
    worker_id: Mapped[str | None] = mapped_column(String(255))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    # Langfuse trace id (32 hex chars), set by the worker when the trace is opened.
    trace_id: Mapped[str | None] = mapped_column(String(32))
    # Sequence of the latest `run_event` row; the next event is `last_seq + 1`.
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageModel(Base, TimestampMixin):
    """A user or assistant message; ``parts`` is the AI SDK UI message shape, persisted as-is."""

    __tablename__ = "message"
    __table_args__ = (
        UniqueConstraint("conversation_id", "position"),
        CheckConstraint("role IN ('user', 'assistant')", name="role"),
    )

    # Leading column of the unique constraint, so it needs no index of its own.
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE")
    )
    # The run that produced an assistant message (the stream's `start.messageId` is this row).
    run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("run.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"))
    role: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)
    parts: Mapped[list[JsonObject]] = mapped_column(JSONB)
    provider: Mapped[str | None] = mapped_column(String(20))
    model: Mapped[str | None] = mapped_column(String(100))
    # The turn's LangChain messages (`langchain_core.load.dumpd`): AIMessages keep provider
    # thinking blocks and signatures, ToolMessages keep results — replayed verbatim on the same
    # provider; cross-provider history is rebuilt from `parts`.
    provider_messages: Mapped[list[JsonObject] | None] = mapped_column(JSONB)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)


class RunEventModel(Base, TimestampMixin):
    """One UI message chunk of a run, in order. ``payload`` is the chunk itself (``type`` is
    duplicated so terminal events are found without unpacking JSON)."""

    __tablename__ = "run_event"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("run.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[JsonObject] = mapped_column(JSONB)
