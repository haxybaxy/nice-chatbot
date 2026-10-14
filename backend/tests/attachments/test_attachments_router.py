"""HTTP tests for the attachments API: upload (every kind, the extension fallback, the limits),
metadata, content download with its headers, and the delete rules."""

from collections.abc import Callable
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import AttachmentBlobModel, AttachmentModel
from app.chat.models import MessageRole
from app.core.config import attachment_settings
from app.organizations.models import OrganizationModel, OrganizationRole
from app.teams.models import TeamModel
from app.users.models import UserModel
from tests.sample_files import DOCX_TYPE, PNG_1X1, docx_bytes, minimal_pdf
from tests.seeds import (
    seed_attachment,
    seed_conversation,
    seed_member,
    seed_message,
    seed_organization,
    seed_team,
    seed_team_member,
    seed_user,
)

type Authenticate = Callable[[UserModel], None]
type Upload = tuple[str, bytes, str]  # (filename, bytes, declared media type)


@pytest.fixture
async def owner(db_session: AsyncSession) -> UserModel:
    return await seed_user(db_session, email="owner@example.com", full_name="Org Owner")


@pytest.fixture
async def organization(db_session: AsyncSession, owner: UserModel) -> OrganizationModel:
    return await seed_organization(db_session, name="Nice Chatbot", owner=owner)


@pytest.fixture
async def team(db_session: AsyncSession, organization: OrganizationModel, owner: UserModel) -> TeamModel:
    return await seed_team(db_session, organization=organization, name="Research", creator=owner)


@pytest.fixture
async def member(db_session: AsyncSession, organization: OrganizationModel, team: TeamModel) -> UserModel:
    user = await seed_user(db_session, email="member@example.com", full_name="Team Member")
    await seed_member(db_session, organization, user, OrganizationRole.MEMBER)
    await seed_team_member(db_session, team, user)
    return user


@pytest.fixture
async def outsider(db_session: AsyncSession) -> UserModel:
    return await seed_user(db_session, email="outsider@example.com")


@pytest.fixture
async def attachment(db_session: AsyncSession, team: TeamModel, owner: UserModel) -> AttachmentModel:
    return await seed_attachment(db_session, team=team, uploader=owner, filename="résumé notes.txt")


async def _row(db: AsyncSession, attachment_id: UUID) -> AttachmentModel | None:
    return await db.get(AttachmentModel, attachment_id, populate_existing=True)


async def _blob(db: AsyncSession, attachment_id: UUID) -> bytes | None:
    result = await db.execute(
        select(AttachmentBlobModel.data).where(AttachmentBlobModel.attachment_id == attachment_id)
    )
    return result.scalar_one_or_none()


def _files(upload: Upload) -> dict[str, Upload]:
    return {"file": upload}


class TestUpload:
    @pytest.mark.parametrize(
        ("upload", "kind", "media_type", "has_text"),
        [
            (("pixel.png", PNG_1X1, "image/png"), "image", "image/png", False),
            (("report.pdf", minimal_pdf("Hello PDF"), "application/pdf"), "pdf", "application/pdf", True),
            (("memo.docx", docx_bytes(["Hello docx"]), DOCX_TYPE), "docx", DOCX_TYPE, True),
            (("notes.txt", b"plain notes", "text/plain; charset=utf-8"), "text", "text/plain", True),
            # Browsers send octet-stream (or nothing) for source files: the extension decides.
            (("script.py", b"print(1)\n", "application/octet-stream"), "text", "text/plain", True),
            (("README.md", b"# Title", ""), "text", "text/markdown", True),
            # A wrong guess (`.ts` as MPEG transport stream) is overruled by the extension.
            (("app.ts", b"export {}", "video/mp2t"), "text", "application/typescript", True),
            (("Dockerfile", b"FROM python:3.13", "application/octet-stream"), "text", "text/plain", True),
        ],
        ids=["png", "pdf", "docx", "txt", "py", "md", "ts", "dockerfile"],
    )
    async def test_stores_the_file_and_extracts_its_text(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        owner: UserModel,
        authenticate_as: Authenticate,
        upload: Upload,
        kind: str,
        media_type: str,
        has_text: bool,
    ) -> None:
        authenticate_as(owner)
        filename, data, _ = upload

        response = await client.post(f"/api/teams/{team.id}/attachments", files=_files(upload))

        assert response.status_code == 201, response.text
        body = response.json()
        assert (body["teamId"], body["filename"], body["mediaType"], body["kind"]) == (
            str(team.id),
            filename,
            media_type,
            kind,
        )
        assert body["sizeBytes"] == len(data)
        assert body["messageId"] is None
        assert body["extractionError"] is None
        assert body["url"] == f"/api/attachments/{body['id']}/content"
        assert (body["textChars"] is not None and body["textChars"] > 0) is has_text
        row = await _row(db_session, UUID(body["id"]))
        assert row is not None
        assert (row.uploaded_by, row.kind, row.media_type) == (owner.id, kind, media_type)
        assert (row.extracted_text is not None) is has_text
        assert await _blob(db_session, row.id) == data

    async def test_extraction_failure_does_not_fail_the_upload(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(owner)

        response = await client.post(
            f"/api/teams/{team.id}/attachments", files=_files(("broken.pdf", b"%PDF-1.4 not really", "application/pdf"))
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["kind"] == "pdf"
        assert body["textChars"] is None
        assert body["extractionError"]
        row = await _row(db_session, UUID(body["id"]))
        assert row is not None
        assert (row.extracted_text, row.extraction_error) == (None, body["extractionError"])

    async def test_too_large_is_400_and_nothing_is_stored(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        owner: UserModel,
        authenticate_as: Authenticate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(attachment_settings, "attachment_max_bytes", 16)
        authenticate_as(owner)

        response = await client.post(
            f"/api/teams/{team.id}/attachments", files=_files(("big.txt", b"x" * 17, "text/plain"))
        )

        assert response.status_code == 400, response.text
        body = response.json()
        assert body["code"] == "BAD_REQUEST"
        assert body["details"] == {"maxBytes": 16, "filename": "big.txt"}
        assert (await db_session.execute(select(AttachmentModel))).scalars().all() == []

        exact = await client.post(
            f"/api/teams/{team.id}/attachments", files=_files(("fits.txt", b"x" * 16, "text/plain"))
        )
        assert exact.status_code == 201

    async def test_unsupported_type_is_400(
        self, client: AsyncClient, team: TeamModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.post(
            f"/api/teams/{team.id}/attachments", files=_files(("archive.zip", b"PK\x03\x04", "application/zip"))
        )

        assert response.status_code == 400
        assert response.json()["details"] == {"mediaType": "application/zip", "filename": "archive.zip"}

    async def test_non_member_gets_404(
        self, client: AsyncClient, team: TeamModel, outsider: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(outsider)

        response = await client.post(f"/api/teams/{team.id}/attachments", files=_files(("a.txt", b"a", "text/plain")))

        assert response.status_code == 404


class TestGetAttachment:
    async def test_members_read_the_metadata(
        self, client: AsyncClient, attachment: AttachmentModel, member: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(member)

        response = await client.get(f"/api/attachments/{attachment.id}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == str(attachment.id)
        assert body["filename"] == "résumé notes.txt"
        assert body["textChars"] == len("hello from notes")
        assert body["url"] == f"/api/attachments/{attachment.id}/content"

    async def test_non_member_and_unknown_are_404(
        self, client: AsyncClient, attachment: AttachmentModel, outsider: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(outsider)
        assert (await client.get(f"/api/attachments/{attachment.id}")).status_code == 404
        assert (await client.get(f"/api/attachments/{uuid4()}")).status_code == 404


class TestGetContent:
    async def test_serves_the_bytes_inline_with_the_download_headers(
        self, client: AsyncClient, attachment: AttachmentModel, member: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(member)

        response = await client.get(f"/api/attachments/{attachment.id}/content")

        assert response.status_code == 200
        assert response.content == b"hello from notes"
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert response.headers["content-length"] == str(len(b"hello from notes"))
        encoded = quote("résumé notes.txt", safe="")
        assert response.headers["content-disposition"] == f"inline; filename*=UTF-8''{encoded}"
        assert response.headers["cache-control"] == "private, max-age=3600"
        assert response.headers["x-content-type-options"] == "nosniff"

    async def test_download_flag_asks_the_browser_to_save(
        self, client: AsyncClient, attachment: AttachmentModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.get(f"/api/attachments/{attachment.id}/content", params={"download": "true"})

        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")

    async def test_non_member_gets_a_json_404(
        self, client: AsyncClient, attachment: AttachmentModel, outsider: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(outsider)

        response = await client.get(f"/api/attachments/{attachment.id}/content")

        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["code"] == "NOT_FOUND"


class TestDeleteAttachment:
    async def test_uploader_deletes_an_unsent_upload_with_its_bytes(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        attachment: AttachmentModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(owner)

        response = await client.delete(f"/api/attachments/{attachment.id}")

        assert response.status_code == 204
        assert await _row(db_session, attachment.id) is None
        assert await _blob(db_session, attachment.id) is None

    async def test_refused_once_a_message_carries_it(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        conversation = await seed_conversation(db_session, team=team, creator=owner)
        message = await seed_message(db_session, conversation=conversation, role=MessageRole.USER, position=0)
        sent = await seed_attachment(db_session, team=team, uploader=owner, message=message)
        authenticate_as(owner)

        response = await client.delete(f"/api/attachments/{sent.id}")

        assert response.status_code == 409
        assert await _row(db_session, sent.id) is not None

    async def test_another_member_is_403_and_an_outsider_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        attachment: AttachmentModel,
        member: UserModel,
        outsider: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(member)
        assert (await client.delete(f"/api/attachments/{attachment.id}")).status_code == 403

        authenticate_as(outsider)
        assert (await client.delete(f"/api/attachments/{attachment.id}")).status_code == 404
        assert (await client.delete(f"/api/attachments/{uuid4()}")).status_code == 404
        assert await _row(db_session, attachment.id) is not None
