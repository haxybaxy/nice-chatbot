"""Read LangChain message content the way the stream mapper needs it: text and reasoning fragments, tool results."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal, cast

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

type Fragment = tuple[Literal["text", "reasoning"], str]


def _fragment(item: Mapping[str, object]) -> Fragment | None:
    kind = item.get("type")
    if kind == "text":
        text = item.get("text")
        return ("text", text) if isinstance(text, str) and text else None
    if kind in ("reasoning", "thinking"):
        text = item.get("reasoning") if kind == "reasoning" else item.get("thinking")
        return ("reasoning", text) if isinstance(text, str) and text else None
    return None


def fragments(content: object) -> Iterable[Fragment]:
    """Text and reasoning fragments of a message's content, in order (tool blocks are skipped)."""
    if isinstance(content, str):
        if content:
            yield "text", content
        return
    if not isinstance(content, list):
        return
    for block in cast("list[object]", content):
        if isinstance(block, str):
            if block:
                yield "text", block
        elif isinstance(block, Mapping):
            fragment = _fragment(cast("Mapping[str, object]", block))
            if fragment is not None:
                yield fragment


def text_of(message: BaseMessage) -> str:
    return "".join(text for kind, text in fragments(message.content) if kind == "text")


def tool_messages(update: Mapping[str, object]) -> list[ToolMessage]:
    messages = update.get("messages")
    if not isinstance(messages, list):
        return []
    return [message for message in cast("list[object]", messages) if isinstance(message, ToolMessage)]


def ai_messages(update: Mapping[str, object]) -> list[AIMessage]:
    messages = update.get("messages")
    if not isinstance(messages, list):
        return []
    return [message for message in cast("list[object]", messages) if isinstance(message, AIMessage)]
