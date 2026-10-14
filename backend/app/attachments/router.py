"""Attachment routes: upload into a team, read the metadata, download the bytes, delete an
unsent upload. Attachments are bound to a message by ``POST …/messages`` (chat domain)."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.attachments.dependencies import (
    AttachmentAccessDep,
    DeleteAttachmentDep,
    GetAttachmentContentDep,
    TeamAccessDep,
    UploadAttachmentDep,
    UploadDep,
)
from app.attachments.models import AttachmentModel
from app.attachments.schemas import AttachmentOut
from app.core.downloads import AttachmentContentResponse
from app.core.openapi import error_responses
from app.core.security import CurrentUserDep

router = APIRouter(tags=["attachments"], responses=error_responses(401))

_CONTENT_DESCRIPTION = (
    "The stored bytes under the attachment's media type. `Content-Disposition` is `inline` (or "
    "`attachment` with `?download=true`) with the RFC 5987 encoded filename; cached privately for an hour."
)


@router.post(
    "/teams/{team_id}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an attachment",
    responses=error_responses(400, 404, 422),
)
async def upload_attachment(
    upload: UploadDep, membership: TeamAccessDep, use_case: UploadAttachmentDep
) -> AttachmentModel:
    """Multipart with one `file` field. Text is extracted at once (PDF, DOCX, text and code files;
    images have none). 400 for an unsupported type or a file over the size limit. The attachment
    is yours alone until a message is created with it; unsent uploads are swept after a day."""
    return await use_case.execute(
        team_id=membership.team_id,
        uploader=membership.user,
        filename=upload.filename,
        media_type=upload.media_type,
        data=upload.data,
    )


@router.get(
    "/attachments/{attachment_id}",
    response_model=AttachmentOut,
    summary="Get an attachment's metadata",
    responses=error_responses(404, 422),
)
async def get_attachment(attachment: AttachmentAccessDep) -> AttachmentModel:
    """Visible to every member of the attachment's team."""
    return attachment


@router.get(
    "/attachments/{attachment_id}/content",
    response_class=AttachmentContentResponse,
    summary="Download an attachment's content",
    responses={
        **error_responses(404, 422),
        200: {
            "description": _CONTENT_DESCRIPTION,
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        },
    },
)
async def get_attachment_content(
    attachment: AttachmentAccessDep,
    use_case: GetAttachmentContentDep,
    download: Annotated[bool, Query(description="Serve as `Content-Disposition: attachment`")] = False,
) -> AttachmentContentResponse:
    data = await use_case.execute(attachment=attachment)
    return AttachmentContentResponse(
        data, media_type=attachment.media_type, filename=attachment.filename, download=download
    )


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unsent attachment",
    responses=error_responses(403, 404, 409, 422),
)
async def delete_attachment(
    attachment: AttachmentAccessDep, current_user: CurrentUserDep, use_case: DeleteAttachmentDep
) -> None:
    """Only the uploader (403 otherwise), and only before a message carries it (409 after)."""
    await use_case.execute(attachment=attachment, actor=current_user)
