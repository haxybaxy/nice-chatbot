from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import AttachmentModel
from app.attachments.repository import AttachmentRepository


class GetAttachmentContent:
    """The bytes of an attachment the route's dependency already resolved and authorized."""

    def __init__(self, session: AsyncSession) -> None:
        self._attachments = AttachmentRepository(session)

    async def execute(self, *, attachment: AttachmentModel) -> bytes:
        return await self._attachments.get_blob(attachment.id)
