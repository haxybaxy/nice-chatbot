from datetime import UTC, datetime, timedelta

from app.attachments.repository import AttachmentRepository
from app.core.config import attachment_settings
from app.db.session import SessionScope


class ReapOrphanAttachments:
    """Delete uploads never bound to a message (``message_id`` NULL) older than
    ``ATTACHMENT_ORPHAN_TTL_HOURS`` — abandoned uploads, and attachments whose message went with a
    deleted conversation (the FK sets ``message_id`` to NULL). Runs in the worker's reaper loop
    next to ``ReapStaleRuns`` (which logs the count); returns how many were deleted."""

    def __init__(self, sessions: SessionScope) -> None:
        self._sessions = sessions

    async def execute(self) -> int:
        threshold = datetime.now(UTC) - timedelta(hours=attachment_settings.attachment_orphan_ttl_hours)
        async with self._sessions() as session:
            return await AttachmentRepository(session).delete_orphans_before(threshold)
