from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import AttachmentModel
from app.attachments.repository import AttachmentRepository
from app.core.config import attachment_settings
from app.core.exceptions import AppError


class ClaimAttachmentsForMessage:
    """Bind uploads to the user message being created — the attachments domain's public surface
    for the chat domain.

    Every id must name an upload of ``uploader_id`` in ``team_id`` (otherwise 404, without
    revealing whether it exists), not yet bound to a message (409), at most
    ``ATTACHMENT_MAX_PER_MESSAGE`` of them and no id twice (400). The rows are locked so two
    messages cannot claim the same upload; the claimed rows come back in the order given.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._attachments = AttachmentRepository(session)

    async def execute(
        self, *, attachment_ids: Sequence[UUID], team_id: UUID, uploader_id: UUID, message_id: UUID
    ) -> list[AttachmentModel]:
        if not attachment_ids:
            return []
        limit = attachment_settings.attachment_max_per_message
        if len(attachment_ids) > limit:
            raise AppError.bad_request("Too many attachments", details={"max": limit, "count": len(attachment_ids)})
        if len(set(attachment_ids)) != len(attachment_ids):
            raise AppError.bad_request("An attachment is listed twice")
        by_id = {row.id: row for row in await self._attachments.lock_many(attachment_ids)}
        claimed: list[AttachmentModel] = []
        for attachment_id in attachment_ids:
            row = by_id.get(attachment_id)
            if row is None or row.team_id != team_id or row.uploaded_by != uploader_id:
                raise AppError.not_found("Attachment", attachment_id)
            if row.message_id is not None:
                raise AppError.conflict(
                    "Attachment is already attached to a message", details={"attachmentId": str(attachment_id)}
                )
            row.message_id = message_id
            claimed.append(row)
        await self._attachments.save_all(claimed)
        return claimed
