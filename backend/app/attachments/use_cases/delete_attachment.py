from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import AttachmentModel
from app.attachments.repository import AttachmentRepository
from app.core.exceptions import AppError
from app.users.models import UserModel


class DeleteAttachment:
    """Remove an upload before it is sent: only its uploader may (403), and only while no message
    carries it (409) — a message's attachments stay with the message."""

    def __init__(self, session: AsyncSession) -> None:
        self._attachments = AttachmentRepository(session)

    async def execute(self, *, attachment: AttachmentModel, actor: UserModel) -> None:
        if attachment.uploaded_by != actor.id:
            raise AppError.forbidden("Only the uploader can delete an attachment")
        if attachment.message_id is not None:
            raise AppError.conflict("The attachment is already part of a message")
        await self._attachments.delete(attachment)
