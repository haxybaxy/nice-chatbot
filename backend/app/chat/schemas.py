"""HTTP schemas for the chat API.

``MessagePartOut`` mirrors the AI SDK UI message part shape that ``message.parts`` persists (and
that ``useChat`` builds client-side from the same stream), so a message loaded over REST and one
rebuilt from a replayed stream are identical. Part dicts carry the wire keys already
(``sourceId``, ``toolCallId``); the alias generator maps them to the snake_case fields.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Discriminator, Field, Tag

from app.chat.models import ConversationVisibility, MessageRole, RunMode, RunStatus
from app.core.config import Effort, LlmProvider
from app.core.llm.catalog import Tier
from app.core.schemas import BaseSchema, BaseSchemaOut, UtcDatetime, type_tag

# ── Message parts (the persisted UI message shape) ────────────────────────────

type PartState = Literal["streaming", "done"]


class TextPartOut(BaseSchemaOut):
    type: Literal["text"]
    text: str
    state: PartState | None = None


class ReasoningPartOut(BaseSchemaOut):
    type: Literal["reasoning"]
    text: str
    state: PartState | None = None


class StepStartPartOut(BaseSchemaOut):
    type: Literal["step-start"]


class SourceUrlPartOut(BaseSchemaOut):
    type: Literal["source-url"]
    source_id: str
    url: str
    title: str | None = None


class ToolPartOut(BaseSchemaOut):
    """``tool-<name>``: a tool call with its input and, once run, its output or error."""

    type: str = Field(pattern=r"^tool-")
    tool_call_id: str
    state: Literal["input-available", "output-available", "output-error"]
    input: object | None = None
    output: object | None = None
    error_text: str | None = None


class DataPartOut(BaseSchemaOut):
    """``data-<name>``: a typed side channel the UI renders itself (research progress, …)."""

    type: str = Field(pattern=r"^data-")
    id: str | None = None
    data: object


type MessagePartOut = Annotated[
    Annotated[TextPartOut, Tag("text")]
    | Annotated[ReasoningPartOut, Tag("reasoning")]
    | Annotated[StepStartPartOut, Tag("step-start")]
    | Annotated[SourceUrlPartOut, Tag("source-url")]
    | Annotated[ToolPartOut, Tag("tool")]
    | Annotated[DataPartOut, Tag("data")],
    Discriminator(type_tag({"tool-": "tool", "data-": "data"})),
]


# ── Outputs ──────────────────────────────────────────────────────────────────


class RunOptionsOut(BaseSchemaOut):
    web_search: bool
    code: bool


class RunOut(BaseSchemaOut):
    id: UUID
    conversation_id: UUID
    status: RunStatus
    mode: RunMode
    model: str
    provider: LlmProvider
    effort: Effort
    options: RunOptionsOut
    attempt: int
    last_seq: int
    trace_id: str | None = None
    error: str | None = None
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    cancel_requested_at: UtcDatetime | None = None


class MessageOut(BaseSchemaOut):
    id: UUID
    conversation_id: UUID
    run_id: UUID | None = None
    created_by: UUID | None = None
    role: MessageRole
    position: int
    parts: list[MessagePartOut]
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ConversationOut(BaseSchemaOut):
    id: UUID
    team_id: UUID
    created_by: UUID | None = None
    title: str | None = None
    visibility: ConversationVisibility
    model: str | None = None
    last_message_at: UtcDatetime
    created_at: UtcDatetime
    updated_at: UtcDatetime
    active_run: RunOut | None = None


class ConversationDetailOut(BaseSchemaOut):
    conversation: ConversationOut
    messages: list[MessageOut]


class ConversationPageOut(BaseSchemaOut):
    items: list[ConversationOut]
    next_cursor: str | None = None


class ModelOut(BaseSchemaOut):
    """One entry of the model picker, built from the catalog's ``ModelSpec`` by attribute."""

    id: str
    provider: LlmProvider
    model_id: str
    display_name: str
    tier: Tier
    supports_tools: bool
    supports_reasoning: bool
    is_default: bool


# ── Inputs ───────────────────────────────────────────────────────────────────


class TextPartIn(BaseSchema):
    type: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=32_000)


class RunOptionsIn(BaseSchema):
    # web_search enables both the `web_search` and `web_fetch` tools.
    web_search: bool = True
    code: bool = False


class CreateMessageIn(BaseSchema):
    parts: list[TextPartIn] = Field(min_length=1, max_length=8)
    # A catalog id ("anthropic:claude-opus-5-5"); the catalog default when omitted.
    model: str | None = Field(default=None, max_length=100)
    mode: RunMode = RunMode.CHAT
    tools: RunOptionsIn = Field(default_factory=RunOptionsIn)


class CreateConversationIn(BaseSchema):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    visibility: ConversationVisibility = ConversationVisibility.TEAM
    # Sent along, the first user message is queued in the same transaction.
    message: CreateMessageIn | None = None


class UpdateConversationIn(BaseSchema):
    """Omitted fields stay as they are."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    visibility: ConversationVisibility | None = None
