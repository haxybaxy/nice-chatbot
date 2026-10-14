import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import ConversationModel
from app.chat.repository import ConversationRepository
from app.core.exceptions import AppError

_CURSOR_SEPARATOR = "|"


@dataclass(frozen=True, slots=True)
class ConversationPage:
    items: Sequence[ConversationModel]
    next_cursor: str | None


def _encode_cursor(conversation: ConversationModel) -> str:
    raw = f"{conversation.last_message_at.isoformat()}{_CURSOR_SEPARATOR}{conversation.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        timestamp, _, identifier = raw.partition(_CURSOR_SEPARATOR)
        return datetime.fromisoformat(timestamp), UUID(identifier)
    except ValueError as error:  # binascii.Error and UnicodeDecodeError are ValueErrors
        raise AppError.bad_request("Invalid cursor") from error


class ListConversations:
    """A team's conversations, newest activity first, keyset-paginated on
    ``(last_message_at desc, id desc)`` behind an opaque urlsafe cursor."""

    def __init__(self, session: AsyncSession) -> None:
        self._conversations = ConversationRepository(session)

    async def execute(self, *, team_id: UUID, viewer_id: UUID, cursor: str | None, limit: int) -> ConversationPage:
        after = _decode_cursor(cursor) if cursor else None
        rows = await self._conversations.list_for_team(team_id, viewer_id=viewer_id, after=after, limit=limit + 1)
        items = rows[:limit]
        next_cursor = _encode_cursor(items[-1]) if len(rows) > limit else None
        return ConversationPage(items=items, next_cursor=next_cursor)
