"""Data access for conversations, messages, runs and run events. Flushes, never commits.

Run rows double as the work queue: ``RunRepository`` holds the row-locking queries the worker
and the reaper rely on (``FOR UPDATE SKIP LOCKED`` claims, lease-fenced locks) and the
``pg_notify`` call that wakes listeners in the writer's transaction.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Row, func, or_, select, text, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import (
    ACTIVE_RUN_STATUSES,
    ConversationModel,
    ConversationVisibility,
    MessageModel,
    RunEventModel,
    RunModel,
    RunStatus,
)
from app.core.ui_stream import UIChunk


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, conversation: ConversationModel) -> ConversationModel:
        self._session.add(conversation)
        await self._session.flush()
        await self._session.refresh(conversation)
        return conversation

    async def save(self, conversation: ConversationModel) -> ConversationModel:
        await self._session.flush()
        await self._session.refresh(conversation)
        return conversation

    async def refresh_active_run(self, conversation: ConversationModel) -> None:
        await self._session.refresh(conversation, ["active_run"])

    async def get_by_id(self, conversation_id: UUID) -> ConversationModel | None:
        return await self._session.get(ConversationModel, conversation_id)

    async def lock(self, conversation_id: UUID) -> ConversationModel | None:
        """``SELECT … FOR UPDATE``: serializes message creation per conversation."""
        result = await self._session.execute(
            select(ConversationModel).where(ConversationModel.id == conversation_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_for_team(
        self, team_id: UUID, *, viewer_id: UUID, after: tuple[datetime, UUID] | None, limit: int
    ) -> Sequence[ConversationModel]:
        """Newest activity first, keyset-paginated on ``(last_message_at, id)``; private
        conversations only for their creator."""
        query = (
            select(ConversationModel)
            .where(
                ConversationModel.team_id == team_id,
                or_(
                    ConversationModel.visibility == ConversationVisibility.TEAM.value,
                    ConversationModel.created_by == viewer_id,
                ),
            )
            .order_by(ConversationModel.last_message_at.desc(), ConversationModel.id.desc())
            .limit(limit)
        )
        if after is not None:
            query = query.where(tuple_(ConversationModel.last_message_at, ConversationModel.id) < after)
        result = await self._session.execute(query)
        return result.scalars().all()

    async def delete(self, conversation: ConversationModel) -> None:
        await self._session.delete(conversation)
        await self._session.flush()


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, message: MessageModel) -> MessageModel:
        self._session.add(message)
        await self._session.flush()
        await self._session.refresh(message)
        return message

    async def save(self, message: MessageModel) -> MessageModel:
        await self._session.flush()
        await self._session.refresh(message)
        return message

    async def list_for_conversation(self, conversation_id: UUID) -> Sequence[MessageModel]:
        result = await self._session.execute(
            select(MessageModel).where(MessageModel.conversation_id == conversation_id).order_by(MessageModel.position)
        )
        return result.scalars().all()

    async def next_position(self, conversation_id: UUID) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(MessageModel.position), -1)).where(
                MessageModel.conversation_id == conversation_id
            )
        )
        return int(result.scalar_one()) + 1

    async def get_by_run(self, run_id: UUID) -> MessageModel | None:
        result = await self._session.execute(select(MessageModel).where(MessageModel.run_id == run_id))
        return result.scalar_one_or_none()


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, run: RunModel) -> RunModel:
        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def save(self, run: RunModel) -> RunModel:
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def get_by_id(self, run_id: UUID) -> RunModel | None:
        return await self._session.get(RunModel, run_id)

    async def get_status(self, run_id: UUID) -> str | None:
        result = await self._session.execute(select(RunModel.status).where(RunModel.id == run_id))
        return result.scalar_one_or_none()

    async def get_active(self, conversation_id: UUID) -> RunModel | None:
        result = await self._session.execute(
            select(RunModel).where(
                RunModel.conversation_id == conversation_id, RunModel.status.in_(ACTIVE_RUN_STATUSES)
            )
        )
        return result.scalar_one_or_none()

    async def lock(self, run_id: UUID) -> RunModel | None:
        """``SELECT … FOR UPDATE`` on one run (cancel vs. claim/finish races)."""
        result = await self._session.execute(select(RunModel).where(RunModel.id == run_id).with_for_update())
        return result.scalar_one_or_none()

    async def lock_owned(self, run_id: UUID, worker_id: str) -> RunModel | None:
        """The run locked for this worker, or ``None`` when the lease is gone (re-queued by the
        reaper, or finished) — the fence every worker write passes through."""
        result = await self._session.execute(
            select(RunModel)
            .where(RunModel.id == run_id, RunModel.worker_id == worker_id, RunModel.status == RunStatus.RUNNING.value)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def lock_next_queued(self) -> RunModel | None:
        """The oldest queued run, locked and skipping rows other workers hold (``SKIP LOCKED``)."""
        result = await self._session.execute(
            select(RunModel)
            .where(RunModel.status == RunStatus.QUEUED.value)
            .order_by(RunModel.created_at, RunModel.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return result.scalar_one_or_none()

    async def lock_stale(self, heartbeat_before: datetime) -> Sequence[RunModel]:
        """Running runs whose worker stopped heartbeating, locked for the reaper."""
        result = await self._session.execute(
            select(RunModel)
            .where(RunModel.status == RunStatus.RUNNING.value, RunModel.heartbeat_at < heartbeat_before)
            .order_by(RunModel.created_at, RunModel.id)
            .with_for_update(skip_locked=True)
        )
        return result.scalars().all()

    async def touch(self, run_id: UUID, worker_id: str, now: datetime) -> Row[tuple[datetime | None]] | None:
        """Heartbeat in one fenced statement. ``None`` when the lease is gone; otherwise a row
        holding the run's ``cancel_requested_at`` (``None`` while nobody asked it to stop)."""
        result = await self._session.execute(
            update(RunModel)
            .where(RunModel.id == run_id, RunModel.worker_id == worker_id, RunModel.status == RunStatus.RUNNING.value)
            .values(heartbeat_at=now)
            .returning(RunModel.cancel_requested_at)
            .execution_options(synchronize_session=False)
        )
        return result.first()

    async def notify(self, channel: str, payload: str) -> None:
        """``pg_notify`` inside the current transaction: delivered only if it commits."""
        await self._session.execute(
            text("SELECT pg_notify(:channel, :payload)"), {"channel": channel, "payload": payload}
        )


class RunEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_batch(self, run_id: UUID, first_seq: int, chunks: Sequence[UIChunk]) -> None:
        """Persist ``chunks`` at ``first_seq, first_seq + 1, …``."""
        self._session.add_all(
            RunEventModel(run_id=run_id, seq=first_seq + offset, type=chunk["type"], payload=dict(chunk))
            for offset, chunk in enumerate(chunks)
        )
        await self._session.flush()

    async def list_all(self, run_id: UUID) -> Sequence[RunEventModel]:
        result = await self._session.execute(
            select(RunEventModel).where(RunEventModel.run_id == run_id).order_by(RunEventModel.seq)
        )
        return result.scalars().all()

    async def list_after(self, run_id: UUID, after_seq: int, *, limit: int) -> Sequence[RunEventModel]:
        result = await self._session.execute(
            select(RunEventModel)
            .where(RunEventModel.run_id == run_id, RunEventModel.seq > after_seq)
            .order_by(RunEventModel.seq)
            .limit(limit)
        )
        return result.scalars().all()
