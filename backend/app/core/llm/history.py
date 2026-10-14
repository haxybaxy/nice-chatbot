"""Persisted conversation rows ⇄ LangChain messages.

A stored assistant message keeps two views of the same turn: ``parts`` (the UI message shape, what
the client renders) and ``provider_messages`` (the turn's LangChain messages serialized with
``langchain_core.load.dumpd`` — Anthropic thinking blocks with their signatures, tool calls and
tool results verbatim). Replaying to the *same provider* loads ``provider_messages`` as they were,
so Claude sees its own thinking and tool history (also across Claude models); replaying to another
provider rebuilds neutral ``AIMessage`` / ``ToolMessage`` pairs from ``parts`` with the reasoning
dropped. Histories are append-only: nothing here rewrites what a previous turn stored.

:class:`StoredMessage` is the small read model this module needs; the chat domain maps its ORM
rows onto it so the LLM layer never imports a domain model.
"""

# Library boundary: `langchain_core.load.load` / `dumpd` are typed `Any`.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import json
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast

from langchain_core._api import LangChainBetaWarning
from langchain_core.load import dumpd, load
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.core.llm.catalog import ModelSpec
from app.core.ui_stream import TOOL_PREFIX, JsonObject

NOT_EXECUTED = "Tool call was not executed."


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """One persisted conversation message as the LLM layer sees it."""

    role: Literal["user", "assistant"]
    parts: Sequence[JsonObject]
    # Assistant rows: which provider produced the turn, and its LangChain messages (``dump_turn``).
    provider: str | None = None
    model: str | None = None
    provider_messages: Sequence[JsonObject] | None = None


def text_of_parts(parts: Sequence[JsonObject]) -> str:
    """The text parts of a message joined with blank lines (what a user row says)."""
    texts = [str(part.get("text", "")) for part in parts if part.get("type") == "text"]
    return "\n\n".join(text for text in texts if text)


def dump_turn(messages: Sequence[BaseMessage]) -> list[JsonObject]:
    """Serialize a turn's new messages for ``provider_messages`` (``load`` restores them verbatim)."""
    return [cast(JsonObject, dumpd(message)) for message in messages]


def _load_turn(payloads: Sequence[JsonObject]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LangChainBetaWarning)
        for payload in payloads:
            restored = load(dict(payload), allowed_objects="messages")
            if isinstance(restored, BaseMessage):
                messages.append(restored)
    return messages


def _rebuild_turn(parts: Sequence[JsonObject]) -> list[BaseMessage]:
    """Neutral messages from the UI parts: text + tool calls per step, tool results, no reasoning."""
    messages: list[BaseMessage] = []
    texts: list[str] = []
    calls: list[dict[str, object]] = []
    results: list[ToolMessage] = []

    def flush() -> None:
        text = "\n\n".join(texts)
        if text or calls:
            messages.append(AIMessage(content=text, tool_calls=list(calls)))
            messages.extend(results)
        texts.clear()
        calls.clear()
        results.clear()

    for part in parts:
        part_type = str(part.get("type", ""))
        if part_type == "step-start":
            flush()
        elif part_type == "text":
            text = str(part.get("text", ""))
            if text:
                texts.append(text)
        elif part_type.startswith(TOOL_PREFIX):
            call_id = str(part.get("toolCallId", ""))
            name = part_type.removeprefix(TOOL_PREFIX)
            args = part.get("input")
            calls.append(
                {"name": name, "args": args if isinstance(args, dict) else {}, "id": call_id, "type": "tool_call"}
            )
            results.append(_tool_result_message(part, call_id=call_id, name=name))
    flush()
    return messages


def _tool_result_message(part: JsonObject, *, call_id: str, name: str) -> ToolMessage:
    state = part.get("state")
    if state == "output-available":
        return ToolMessage(content=json.dumps(part.get("output"), ensure_ascii=False), tool_call_id=call_id, name=name)
    if state == "output-error":
        return ToolMessage(
            content=str(part.get("errorText", "Tool failed")), tool_call_id=call_id, name=name, status="error"
        )
    return ToolMessage(content=NOT_EXECUTED, tool_call_id=call_id, name=name, status="error")


def _repair(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Every tool call gets a result and every result follows its call — providers reject anything else."""
    repaired: list[BaseMessage] = []
    pending: dict[str, str] = {}  # tool_call_id → tool name, awaiting a ToolMessage

    def settle_pending() -> None:
        for call_id, name in pending.items():
            repaired.append(ToolMessage(content=NOT_EXECUTED, tool_call_id=call_id, name=name, status="error"))
        pending.clear()

    for message in messages:
        if isinstance(message, ToolMessage):
            if message.tool_call_id in pending:
                del pending[message.tool_call_id]
                repaired.append(message)
            continue  # a result without its call: drop it
        settle_pending()
        if isinstance(message, AIMessage):
            pending.update({str(call["id"]): call["name"] for call in message.tool_calls if call.get("id")})
        repaired.append(message)
    settle_pending()
    return repaired


def to_langchain(rows: Sequence[StoredMessage], target: ModelSpec) -> list[BaseMessage]:
    """The messages to send to ``target`` for a conversation, oldest first."""
    messages: list[BaseMessage] = []
    for row in rows:
        if row.role == "user":
            text = text_of_parts(row.parts)
            if text:
                messages.append(HumanMessage(content=text))
        elif row.provider == target.provider and row.provider_messages:
            messages.extend(_load_turn(row.provider_messages))
        else:
            messages.extend(_rebuild_turn(row.parts))
    return _repair(messages)
