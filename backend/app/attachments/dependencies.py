"""FastAPI dependencies for the attachments domain.

``read_upload`` turns the multipart ``file`` field into an in-memory :class:`UploadedFile`, reading
in chunks and refusing (400) as soon as the body passes ``ATTACHMENT_MAX_BYTES`` — a huge upload is
never assembled in memory. ``get_team_access`` resolves ``{team_id}`` to the caller's membership
(404 otherwise) through the teams domain's public ``FindTeamMembership``, like the chat domain
does; ``get_attachment_access`` resolves ``{attachment_id}`` and requires membership of its team
(404 either way, so a non-member cannot tell whether it exists).
"""

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated
from uuid import UUID

from fastapi import Depends, File, UploadFile

from app.attachments.models import AttachmentModel
from app.attachments.repository import AttachmentRepository
from app.attachments.use_cases.delete_attachment import DeleteAttachment
from app.attachments.use_cases.get_attachment_content import GetAttachmentContent
from app.attachments.use_cases.upload_attachment import UploadAttachment
from app.core.config import attachment_settings
from app.core.exceptions import AppError
from app.core.security import CurrentUserDep
from app.db.session import DbDep
from app.teams.models import TeamMemberModel
from app.teams.use_cases.find_team_membership import FindTeamMembership

_CHUNK_BYTES = 64 * 1024
_FILENAME_MAX = 255
_DEFAULT_FILENAME = "upload"


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """The multipart ``file`` field, read in full (within the size limit)."""

    filename: str
    media_type: str
    data: bytes


def _safe_filename(raw: str | None) -> str:
    """The base name only (a browser sends one, but a client may not), clipped to the column."""
    name = PurePosixPath(PureWindowsPath(raw or "").name).name.strip()
    return (name or _DEFAULT_FILENAME)[:_FILENAME_MAX]


async def read_upload(
    file: Annotated[UploadFile, File(description="The file to attach (one per request)")],
) -> UploadedFile:
    limit = attachment_settings.attachment_max_bytes
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(_CHUNK_BYTES):
        size += len(chunk)
        if size > limit:
            raise AppError.bad_request(
                "File too large", details={"maxBytes": limit, "filename": _safe_filename(file.filename)}
            )
        chunks.append(chunk)
    return UploadedFile(
        filename=_safe_filename(file.filename), media_type=file.content_type or "", data=b"".join(chunks)
    )


UploadDep = Annotated[UploadedFile, Depends(read_upload)]


async def get_team_access(team_id: UUID, current_user: CurrentUserDep, db: DbDep) -> TeamMemberModel:
    membership = await FindTeamMembership(db).execute(team_id=team_id, user_id=current_user.id)
    if membership is None:
        raise AppError.not_found("Team", team_id)
    return membership


TeamAccessDep = Annotated[TeamMemberModel, Depends(get_team_access)]


async def get_attachment_access(attachment_id: UUID, current_user: CurrentUserDep, db: DbDep) -> AttachmentModel:
    attachment = await AttachmentRepository(db).get_by_id(attachment_id)
    if attachment is None:
        raise AppError.not_found("Attachment", attachment_id)
    membership = await FindTeamMembership(db).execute(team_id=attachment.team_id, user_id=current_user.id)
    if membership is None:
        raise AppError.not_found("Attachment", attachment_id)
    return attachment


AttachmentAccessDep = Annotated[AttachmentModel, Depends(get_attachment_access)]


async def upload_attachment_use_case(db: DbDep) -> UploadAttachment:
    return UploadAttachment(db)


async def get_attachment_content_use_case(db: DbDep) -> GetAttachmentContent:
    return GetAttachmentContent(db)


async def delete_attachment_use_case(db: DbDep) -> DeleteAttachment:
    return DeleteAttachment(db)


UploadAttachmentDep = Annotated[UploadAttachment, Depends(upload_attachment_use_case)]
GetAttachmentContentDep = Annotated[GetAttachmentContent, Depends(get_attachment_content_use_case)]
DeleteAttachmentDep = Annotated[DeleteAttachment, Depends(delete_attachment_use_case)]
