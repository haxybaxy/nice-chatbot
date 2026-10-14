"""Seed helpers: async, take the session first, flush, return the model."""

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import AttachmentBlobModel, AttachmentKind, AttachmentModel
from app.auth.models import PasswordResetTokenModel
from app.chat.models import (
    ConversationModel,
    ConversationVisibility,
    MessageModel,
    MessageRole,
    RunEventModel,
    RunMode,
    RunModel,
    RunStatus,
)
from app.core.ui_stream import JsonObject, UIChunk
from app.organizations.models import OrganizationMemberModel, OrganizationModel, OrganizationRole
from app.teams.models import TeamMemberModel, TeamModel
from app.users.models import UserModel


async def seed_user(
    db: AsyncSession, *, email: str, full_name: str | None = None, cognito_sub: str | None = None
) -> UserModel:
    user = UserModel(email=email, full_name=full_name, cognito_sub=cognito_sub or str(uuid4()))
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def seed_organization(db: AsyncSession, *, name: str, owner: UserModel) -> OrganizationModel:
    """An organization with ``owner`` as its owner member."""
    organization = OrganizationModel(name=name, created_by=owner.id)
    db.add(organization)
    await db.flush()
    await seed_member(db, organization, owner, OrganizationRole.OWNER)
    await db.refresh(organization)
    return organization


async def seed_member(
    db: AsyncSession, organization: OrganizationModel, user: UserModel, role: OrganizationRole
) -> OrganizationMemberModel:
    member = OrganizationMemberModel(organization_id=organization.id, user_id=user.id, role=role.value, user=user)
    db.add(member)
    await db.flush()
    return member


async def seed_password_reset_token(
    db: AsyncSession, *, user: UserModel, raw_token: str, expires_in: timedelta = timedelta(minutes=30)
) -> PasswordResetTokenModel:
    """An outstanding reset link for ``user`` (``expires_in`` may be negative for an expired one)."""
    token = PasswordResetTokenModel(
        user_id=user.id,
        token_hash=PasswordResetTokenModel.hash_token(raw_token),
        expires_at=datetime.now(UTC) + expires_in,
    )
    db.add(token)
    await db.flush()
    await db.refresh(token)
    return token


async def seed_team(db: AsyncSession, *, organization: OrganizationModel, name: str, creator: UserModel) -> TeamModel:
    """A team in ``organization`` created by ``creator``, who is its first member."""
    team = TeamModel(organization_id=organization.id, name=name, created_by=creator.id)
    db.add(team)
    await db.flush()
    await seed_team_member(db, team, creator)
    await db.refresh(team)
    return team


async def seed_team_member(db: AsyncSession, team: TeamModel, user: UserModel) -> TeamMemberModel:
    member = TeamMemberModel(team_id=team.id, user_id=user.id, team=team, user=user)
    db.add(member)
    await db.flush()
    return member


async def seed_conversation(
    db: AsyncSession,
    *,
    team: TeamModel,
    creator: UserModel,
    title: str | None = None,
    visibility: ConversationVisibility = ConversationVisibility.TEAM,
    last_message_at: datetime | None = None,
) -> ConversationModel:
    conversation = ConversationModel(team_id=team.id, created_by=creator.id, title=title, visibility=visibility.value)
    if last_message_at is not None:
        conversation.last_message_at = last_message_at
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def seed_message(
    db: AsyncSession,
    *,
    conversation: ConversationModel,
    role: MessageRole,
    position: int,
    parts: list[JsonObject] | None = None,
    run: RunModel | None = None,
    created_by: UserModel | None = None,
    provider_messages: list[JsonObject] | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> MessageModel:
    message = MessageModel(
        conversation_id=conversation.id,
        run_id=run.id if run is not None else None,
        created_by=created_by.id if created_by is not None else None,
        role=role.value,
        position=position,
        parts=parts if parts is not None else [{"type": "text", "text": f"message {position}"}],
        provider=run.provider if run is not None else None,
        model=run.model if run is not None else None,
        provider_messages=provider_messages,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def seed_run(
    db: AsyncSession,
    *,
    conversation: ConversationModel,
    requested_by: UserModel | None,
    status: RunStatus = RunStatus.QUEUED,
    mode: RunMode = RunMode.CHAT,
    model: str = "anthropic:claude-opus-5-5",
    attempt: int = 1,
    worker_id: str | None = None,
    heartbeat_at: datetime | None = None,
    created_at: datetime | None = None,
) -> RunModel:
    """A run in ``status``; ``created_at`` orders the queue, ``heartbeat_at`` ages a running run."""
    run = RunModel(
        conversation_id=conversation.id,
        requested_by=requested_by.id if requested_by is not None else None,
        status=status.value,
        mode=mode.value,
        model=model,
        provider=model.split(":", 1)[0],
        effort="medium",
        options={"web_search": True, "code": False},
        attempt=attempt,
        worker_id=worker_id,
        heartbeat_at=heartbeat_at,
        started_at=heartbeat_at,
    )
    if created_at is not None:
        run.created_at = created_at
    db.add(run)
    await db.flush()
    await db.refresh(run)
    # The conversation may already be loaded in this session: keep its view of the active run current.
    await db.refresh(conversation, ["active_run"])
    return run


async def seed_run_events(db: AsyncSession, run: RunModel, chunks: Sequence[UIChunk]) -> list[RunEventModel]:
    """Append ``chunks`` to the run's log after its current ``last_seq`` (which is advanced)."""
    first_seq = run.last_seq + 1
    events = [
        RunEventModel(run_id=run.id, seq=first_seq + offset, type=chunk["type"], payload=dict(chunk))
        for offset, chunk in enumerate(chunks)
    ]
    db.add_all(events)
    run.last_seq = first_seq + len(chunks) - 1
    await db.flush()
    await db.refresh(run)
    return events


async def seed_attachment(
    db: AsyncSession,
    *,
    team: TeamModel,
    uploader: UserModel,
    filename: str = "notes.txt",
    media_type: str = "text/plain",
    kind: AttachmentKind = AttachmentKind.TEXT,
    data: bytes = b"hello from notes",
    extracted_text: str | None = "hello from notes",
    extraction_error: str | None = None,
    message: MessageModel | None = None,
    created_at: datetime | None = None,
) -> AttachmentModel:
    """An upload in ``team`` by ``uploader`` with its bytes; bound to ``message`` when given,
    otherwise an orphan (``created_at`` ages it for the reaper)."""
    attachment = AttachmentModel(
        team_id=team.id,
        uploaded_by=uploader.id,
        message_id=message.id if message is not None else None,
        filename=filename,
        media_type=media_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        kind=kind.value,
        extracted_text=extracted_text,
        text_chars=len(extracted_text) if extracted_text is not None else None,
        extraction_error=extraction_error,
    )
    if created_at is not None:
        attachment.created_at = created_at
    db.add(attachment)
    await db.flush()
    db.add(AttachmentBlobModel(attachment_id=attachment.id, data=data))
    await db.flush()
    await db.refresh(attachment)
    return attachment
