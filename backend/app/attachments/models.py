"""ORM models for file attachments: the metadata row the API lists and the model reads, and the
bytes in a table of their own so listing an attachment never loads its content.

An attachment is uploaded into a team first (``message_id`` NULL) and bound to a user message when
that message is created; an upload never bound is an orphan the worker's reaper deletes after
``ATTACHMENT_ORPHAN_TTL_HOURS``. Deleting a conversation cascades to its messages, which sets
``message_id`` back to NULL — the same sweep then removes those attachments. ``kind`` is the
closed list in :class:`AttachmentKind` (a string column with a CHECK, the pattern the chat tables
use); ``extracted_text`` is filled at upload time (PDF, DOCX and text files), never by the worker.
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AttachmentKind(StrEnum):
    IMAGE = "image"  # png, jpeg, gif, webp — sent to vision models as image blocks
    PDF = "pdf"
    DOCX = "docx"
    TEXT = "text"  # text/*, JSON/XML/YAML/TOML, source code, Markdown, CSV


class AttachmentModel(Base, TimestampMixin):
    __tablename__ = "attachment"
    __table_args__ = (CheckConstraint("kind IN ('image', 'pdf', 'docx', 'text')", name="kind"),)

    team_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("team.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"))
    # Set once a message is created with this attachment; NULL marks an orphan (swept by the reaper).
    message_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("message.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    # The canonical media type for the detected kind (what the content route serves it as).
    media_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    # Text extracted at upload, capped at ATTACHMENT_MAX_EXTRACTED_CHARS; `text_chars` is the
    # uncapped count; `extraction_error` is a short reason when the file could not be read.
    extracted_text: Mapped[str | None] = mapped_column(Text)
    text_chars: Mapped[int | None] = mapped_column(Integer)
    extraction_error: Mapped[str | None] = mapped_column(String(255))

    @property
    def url(self) -> str:
        """Where the bytes are served (``AttachmentOut.url`` and the persisted ``file`` part)."""
        return f"/api/attachments/{self.id}/content"


class AttachmentBlobModel(Base, TimestampMixin):
    """The bytes of one attachment. A separate table so metadata queries never touch them; the
    repository exposes it as a blob store (``put_blob`` / ``get_blob``) an object store can replace."""

    __tablename__ = "attachment_blob"

    attachment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("attachment.id", ondelete="CASCADE"), unique=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)
