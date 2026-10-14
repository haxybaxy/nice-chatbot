"""How a user message's attachments reach the model.

A user row with attachments becomes a ``HumanMessage`` whose content is a list of blocks: the
user's own text first, then one block per attachment. A text-bearing attachment (PDF, DOCX, text
and code files — their text was extracted at upload) is an ``<attachment name=… type=… chars=…>``
block holding that text; an image is a standard LangChain image block (``create_image_block``,
base64 + mime type, which ``ChatAnthropic`` and ``ChatOpenAI`` both translate) when the target
model can see images, else a one-line placeholder; a file that could not be read is an empty
``<attachment … unreadable=…/>`` tag. The system prompt tells the model what these are and that
their content is data, not instructions.

The text injected into one turn is capped at ``ATTACHMENT_MODEL_TEXT_CHARS`` across every
attachment in the history window, allocated to the most recent attachments first; whatever does
not fit is cut with a ``[truncated: N more characters]`` marker. A row without attachments keeps
today's plain-string content so cached prompt prefixes of existing conversations stay stable.
"""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from typing import cast
from uuid import UUID

from langchain_core.messages import HumanMessage
from langchain_core.messages.content import create_image_block

from app.core.config import attachment_settings

IMAGE_KIND = "image"
type ContentBlock = str | dict[str, object]


@dataclass(frozen=True, slots=True)
class StoredAttachment:
    """One attachment of a persisted user message as the LLM layer sees it; ``image_bytes`` is set
    only for images (text files travel as ``text``, never as bytes)."""

    attachment_id: UUID
    filename: str
    media_type: str
    kind: str
    size_bytes: int
    text: str | None
    text_chars: int | None
    extraction_error: str | None
    image_bytes: bytes | None


def text_budgets(per_row: Sequence[Sequence[StoredAttachment]], limit: int | None = None) -> list[list[int]]:
    """How many characters of each attachment's text may be sent, row by row, with the newest
    attachments served first from a turn-wide budget (``ATTACHMENT_MODEL_TEXT_CHARS`` by default)."""
    remaining = attachment_settings.attachment_model_text_chars if limit is None else limit
    budgets = [[0] * len(attachments) for attachments in per_row]
    for row_index in reversed(range(len(per_row))):
        for index in reversed(range(len(per_row[row_index]))):
            text = per_row[row_index][index].text
            if text is None:
                continue
            allowed = min(len(text), remaining)
            remaining -= allowed
            budgets[row_index][index] = allowed
    return budgets


def _attribute(value: str) -> str:
    return escape(value, quote=True)


def _text_block(attachment: StoredAttachment, budget: int) -> ContentBlock:
    header = f'name="{_attribute(attachment.filename)}" type="{_attribute(attachment.media_type)}"'
    if attachment.text is None:
        reason = attachment.extraction_error or "no text"
        return {"type": "text", "text": f'<attachment {header} unreadable="{_attribute(reason)}"/>'}
    body = attachment.text[:budget]
    total = attachment.text_chars if attachment.text_chars is not None else len(attachment.text)
    omitted = total - len(body)
    marker = f"\n[truncated: {omitted} more characters]" if omitted > 0 else ""
    return {"type": "text", "text": f'<attachment {header} chars="{total}">\n{body}{marker}\n</attachment>'}


def _image_block(attachment: StoredAttachment, *, supports_vision: bool) -> ContentBlock:
    if supports_vision and attachment.image_bytes is not None:
        encoded = b64encode(attachment.image_bytes).decode("ascii")
        return cast("dict[str, object]", create_image_block(base64=encoded, mime_type=attachment.media_type))
    return {"type": "text", "text": f"[image attached: {attachment.filename} — this model cannot view images]"}


def user_message(
    text: str, attachments: Sequence[StoredAttachment], *, budgets: Sequence[int], supports_vision: bool
) -> HumanMessage | None:
    """The ``HumanMessage`` for one user row: plain text when it has no attachments (``None`` when
    it has nothing at all), otherwise the text followed by one block per attachment."""
    if not attachments:
        return HumanMessage(content=text) if text else None
    blocks: list[ContentBlock] = [{"type": "text", "text": text}] if text else []
    for attachment, budget in zip(attachments, budgets, strict=True):
        if attachment.kind == IMAGE_KIND:
            blocks.append(_image_block(attachment, supports_vision=supports_vision))
        else:
            blocks.append(_text_block(attachment, budget))
    return HumanMessage(content=blocks)
