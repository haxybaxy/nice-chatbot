"""Data access for attachments. Flushes, never commits.

``AttachmentRepository`` covers the metadata rows and, separately, the bytes through a blob-store
shaped surface — ``put_blob(attachment_id, data)`` / ``get_blob(attachment_id)`` — backed today by
the ``attachment_blob`` table. That surface is the seam for an object store: an S3-backed
implementation of the same two methods (keyed by attachment id, with the metadata row staying in
Postgres) replaces the table without touching the use cases.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import AttachmentBlobModel, AttachmentModel
from app.core.exceptions import AppError


class AttachmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, attachment: AttachmentModel) -> AttachmentModel:
        self._session.add(attachment)
        await self._session.flush()
        await self._session.refresh(attachment)
        return attachment

    async def save_all(self, attachments: Sequence[AttachmentModel]) -> None:
        await self._session.flush()
        for attachment in attachments:
            await self._session.refresh(attachment)

    async def get_by_id(self, attachment_id: UUID) -> AttachmentModel | None:
        return await self._session.get(AttachmentModel, attachment_id)

    async def lock_many(self, attachment_ids: Sequence[UUID]) -> Sequence[AttachmentModel]:
        """The given rows locked ``FOR UPDATE`` (two messages must not claim the same upload)."""
        result = await self._session.execute(
            select(AttachmentModel).where(AttachmentModel.id.in_(attachment_ids)).with_for_update()
        )
        return result.scalars().all()

    async def list_for_messages(self, message_ids: Sequence[UUID]) -> Sequence[AttachmentModel]:
        result = await self._session.execute(
            select(AttachmentModel)
            .where(AttachmentModel.message_id.in_(message_ids))
            .order_by(AttachmentModel.created_at, AttachmentModel.id)
        )
        return result.scalars().all()

    async def delete(self, attachment: AttachmentModel) -> None:
        await self._session.delete(attachment)
        await self._session.flush()

    async def delete_orphans_before(self, created_before: datetime) -> int:
        """Delete every attachment never bound to a message and older than ``created_before``;
        the blob rows go with them (``ON DELETE CASCADE``). Returns how many were deleted."""
        result = await self._session.execute(
            delete(AttachmentModel)
            .where(AttachmentModel.message_id.is_(None), AttachmentModel.created_at < created_before)
            .returning(AttachmentModel.id)
            .execution_options(synchronize_session=False)
        )
        return len(result.scalars().all())

    # ── Blob store ───────────────────────────────────────────────────────────

    async def put_blob(self, attachment_id: UUID, data: bytes) -> None:
        self._session.add(AttachmentBlobModel(attachment_id=attachment_id, data=data))
        await self._session.flush()

    async def get_blob(self, attachment_id: UUID) -> bytes:
        result = await self._session.execute(
            select(AttachmentBlobModel.data).where(AttachmentBlobModel.attachment_id == attachment_id)
        )
        data = result.scalar_one_or_none()
        if data is None:
            raise AppError.not_found("Attachment content", attachment_id)
        return data
