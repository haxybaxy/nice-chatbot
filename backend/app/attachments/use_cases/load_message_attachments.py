from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import AttachmentKind, AttachmentModel
from app.attachments.repository import AttachmentRepository


@dataclass(frozen=True, slots=True)
class LoadedAttachment:
    """An attachment row plus its bytes when the model needs them (images only)."""

    attachment: AttachmentModel
    image_bytes: bytes | None


class LoadMessageAttachments:
    """The attachments of the given messages, grouped by message id, for the worker: metadata and
    extracted text for every row, the bytes only for images (text files reach the model through
    ``extracted_text``, never their bytes). Messages without attachments are absent from the result."""

    def __init__(self, session: AsyncSession) -> None:
        self._attachments = AttachmentRepository(session)

    async def execute(self, *, message_ids: Sequence[UUID]) -> Mapping[UUID, Sequence[LoadedAttachment]]:
        if not message_ids:
            return {}
        loaded: dict[UUID, list[LoadedAttachment]] = {}
        for row in await self._attachments.list_for_messages(message_ids):
            image_bytes = await self._attachments.get_blob(row.id) if row.kind == AttachmentKind.IMAGE.value else None
            if row.message_id is not None:
                loaded.setdefault(row.message_id, []).append(LoadedAttachment(attachment=row, image_bytes=image_bytes))
        return loaded
