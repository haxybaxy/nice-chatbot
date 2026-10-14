"""Upload-time processing: which uploads are accepted as which kind, and what text comes out of
PDF, DOCX and text files — including the files that cannot be read."""

import pytest

from app.attachments.models import AttachmentKind
from app.attachments.use_cases.extract_text import ENCRYPTED, NO_TEXT, ExtractText
from app.attachments.use_cases.upload_attachment import classify
from app.core.config import attachment_settings
from app.core.exceptions import AppError
from tests.sample_files import DOCX_TYPE, PNG_1X1, docx_bytes, encrypted_pdf, minimal_pdf


class TestClassify:
    @pytest.mark.parametrize(
        ("filename", "declared", "kind", "media_type"),
        [
            ("a.png", "image/png", AttachmentKind.IMAGE, "image/png"),
            ("photo.JPG", "image/jpeg", AttachmentKind.IMAGE, "image/jpeg"),
            ("photo.jpeg", "application/octet-stream", AttachmentKind.IMAGE, "image/jpeg"),
            ("a.pdf", "application/pdf", AttachmentKind.PDF, "application/pdf"),
            ("a.pdf", "", AttachmentKind.PDF, "application/pdf"),
            ("a.docx", DOCX_TYPE, AttachmentKind.DOCX, DOCX_TYPE),
            ("a.docx", "application/octet-stream", AttachmentKind.DOCX, DOCX_TYPE),
            ("a.txt", "text/plain; charset=UTF-8", AttachmentKind.TEXT, "text/plain"),
            ("a.csv", "text/csv", AttachmentKind.TEXT, "text/csv"),
            ("data.json", "application/json", AttachmentKind.TEXT, "application/json"),
            ("data.json", "application/octet-stream", AttachmentKind.TEXT, "application/json"),
            ("config.yaml", "", AttachmentKind.TEXT, "application/yaml"),
            ("main.rs", "application/octet-stream", AttachmentKind.TEXT, "text/plain"),
            (".env.example", "", AttachmentKind.TEXT, "text/plain"),
            ("Makefile", "", AttachmentKind.TEXT, "text/plain"),
            ("diagram.svg", "image/svg+xml", AttachmentKind.TEXT, "text/plain"),
            ("page.html", "text/html", AttachmentKind.TEXT, "text/html"),
        ],
    )
    def test_accepted_uploads(self, filename: str, declared: str, kind: AttachmentKind, media_type: str) -> None:
        assert classify(filename, declared) == (kind, media_type)

    @pytest.mark.parametrize(
        ("filename", "declared"),
        [
            ("archive.zip", "application/zip"),
            ("binary", "application/octet-stream"),
            ("movie.mp4", "video/mp4"),
            ("book.epub", ""),
            ("photo.heic", "image/heic"),
        ],
    )
    def test_everything_else_is_400(self, filename: str, declared: str) -> None:
        with pytest.raises(AppError) as rejected:
            classify(filename, declared)
        assert rejected.value.status_code == 400
        assert rejected.value.details == {"mediaType": declared, "filename": filename}


class TestExtractText:
    async def test_pdf_pages_are_joined_with_form_feeds(self) -> None:
        extraction = await ExtractText().execute(kind=AttachmentKind.PDF, data=minimal_pdf("Hello PDF", "Page two"))

        assert extraction.error is None
        assert extraction.text == "Hello PDF\fPage two"
        assert extraction.text_chars == len("Hello PDF\fPage two")

    async def test_docx_paragraphs_and_table_cells(self) -> None:
        data = docx_bytes(["First paragraph", "Second"], table=[["name", "qty"], ["bolt", "4"]])

        extraction = await ExtractText().execute(kind=AttachmentKind.DOCX, data=data)

        assert extraction.error is None
        assert extraction.text == "First paragraph\nSecond\nname | qty\nbolt | 4"

    async def test_text_is_decoded_leniently_and_nuls_dropped(self) -> None:
        extraction = await ExtractText().execute(kind=AttachmentKind.TEXT, data=b"caf\xc3\xa9 \xff ok\x00!")

        assert extraction.error is None
        assert extraction.text == "café � ok!"
        assert extraction.text_chars == len("café � ok!")

    async def test_stored_text_is_capped_but_the_count_is_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(attachment_settings, "attachment_max_extracted_chars", 5)

        extraction = await ExtractText().execute(kind=AttachmentKind.TEXT, data=b"0123456789")

        assert (extraction.text, extraction.text_chars, extraction.error) == ("01234", 10, None)

    async def test_corrupt_files_report_an_error_instead_of_failing(self) -> None:
        pdf = await ExtractText().execute(kind=AttachmentKind.PDF, data=b"%PDF-1.4 this is not a pdf")
        docx = await ExtractText().execute(kind=AttachmentKind.DOCX, data=b"not a zip archive")

        for extraction in (pdf, docx):
            assert (extraction.text, extraction.text_chars) == (None, None)
            assert extraction.error
            assert len(extraction.error) <= 255

    async def test_encrypted_pdf_and_blank_pdf(self) -> None:
        encrypted = await ExtractText().execute(kind=AttachmentKind.PDF, data=encrypted_pdf())
        blank = await ExtractText().execute(kind=AttachmentKind.PDF, data=minimal_pdf(""))

        assert (encrypted.text, encrypted.text_chars, encrypted.error) == (None, None, ENCRYPTED)
        assert (blank.text, blank.text_chars, blank.error) == (None, 0, NO_TEXT)

    async def test_images_have_no_text(self) -> None:
        extraction = await ExtractText().execute(kind=AttachmentKind.IMAGE, data=PNG_1X1)

        assert (extraction.text, extraction.text_chars, extraction.error) == (None, None, None)
