"""HTTP schemas for attachments. The upload itself is multipart (``file`` field), so there is no
``*In`` schema; the response is the metadata row plus ``url``, where the bytes are served."""

from uuid import UUID

from app.attachments.models import AttachmentKind
from app.core.schemas import BaseSchemaOut, UtcDatetime


class AttachmentOut(BaseSchemaOut):
    id: UUID
    team_id: UUID
    filename: str
    media_type: str
    size_bytes: int
    kind: AttachmentKind
    # Characters of text extracted at upload (uncapped count), or null for images.
    text_chars: int | None = None
    # Why no text could be extracted (corrupt file, encrypted PDF); the upload still succeeded.
    extraction_error: str | None = None
    # The user message this attachment belongs to; null until one is created with it.
    message_id: UUID | None = None
    # `/api/attachments/{id}/content` — the bytes, served with the stored media type.
    url: str
    created_at: UtcDatetime
