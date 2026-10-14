"""Store an upload: classify it, extract its text, keep the bytes."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.models import AttachmentKind, AttachmentModel
from app.attachments.repository import AttachmentRepository
from app.attachments.use_cases.extract_text import ExtractText
from app.core.exceptions import AppError
from app.users.models import UserModel

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
IMAGE_TYPES: frozenset[str] = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
# Declared types accepted as text besides `text/*`.
TEXT_TYPES: frozenset[str] = frozenset(
    {
        "application/json",
        "application/xml",
        "application/x-yaml",
        "application/yaml",
        "application/javascript",
        "application/typescript",
        "application/toml",
    }
)
# The extension fallback, for browsers that send application/octet-stream, nothing, or a wrong
# guess (`.ts` arrives as video/mp2t): extension → the canonical media type stored and served.
_EXTENSION_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": PDF,
    ".docx": DOCX,
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html",
    ".css": "text/css",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".toml": "application/toml",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".jsx": "application/javascript",
    ".ts": "application/typescript",
    ".tsx": "application/typescript",
}
_PLAIN_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".java", ".go", ".rs", ".rb", ".php", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".kt", ".swift",
        ".scala", ".sql", ".sh", ".bash", ".zsh", ".ps1", ".ini", ".cfg", ".env.example", ".rst", ".txt", ".scss",
        ".tex", ".dockerfile", ".makefile", ".gitignore",
        # SVG is XML on the wire: it is read as text, never shown to the model as an image.
        ".svg",
    }
)  # fmt: skip
_BARE_NAMES: frozenset[str] = frozenset({"dockerfile", "makefile"})
_SUFFIXES: tuple[str, ...] = tuple(sorted({*_EXTENSION_TYPES, *_PLAIN_TEXT_EXTENSIONS}, key=len, reverse=True))


def _kind_of_type(media_type: str) -> AttachmentKind | None:
    """The kind a declared media type maps onto, or ``None`` when it is not one we accept."""
    if media_type in IMAGE_TYPES:
        return AttachmentKind.IMAGE
    if media_type == PDF:
        return AttachmentKind.PDF
    if media_type == DOCX:
        return AttachmentKind.DOCX
    if media_type.startswith("text/") or media_type in TEXT_TYPES:
        return AttachmentKind.TEXT
    return None


def _type_of_extension(filename: str) -> str | None:
    """The canonical media type implied by the filename's extension, or ``None``."""
    lowered = filename.lower()
    if lowered in _BARE_NAMES:
        return "text/plain"
    suffix = next((ext for ext in _SUFFIXES if lowered.endswith(ext)), None)
    return _EXTENSION_TYPES.get(suffix, "text/plain") if suffix is not None else None


def classify(filename: str, declared_type: str) -> tuple[AttachmentKind, str]:
    """``(kind, canonical media type)`` for an upload: the declared type when it is one we
    accept, else the extension; 400 otherwise."""
    media_type = declared_type.split(";", 1)[0].strip().lower()
    kind = _kind_of_type(media_type)
    if kind is None:
        fallback = _type_of_extension(filename)
        kind = _kind_of_type(fallback) if fallback is not None else None
        media_type = fallback or media_type
    if kind is None:
        raise AppError.bad_request("Unsupported file type", details={"mediaType": declared_type, "filename": filename})
    return kind, media_type


class UploadAttachment:
    """Store an upload in ``team_id`` on behalf of ``uploader``: classify it (400 for a type we do not
    accept), extract its text (never failing the upload), and keep the bytes in the blob store.
    The route's dependency has already enforced the size limit and the team membership. The
    attachment is unbound (``message_id`` NULL) until a message is created with it."""

    def __init__(self, session: AsyncSession) -> None:
        self._attachments = AttachmentRepository(session)
        self._extract = ExtractText()

    async def execute(
        self, *, team_id: UUID, uploader: UserModel, filename: str, media_type: str, data: bytes
    ) -> AttachmentModel:
        kind, canonical_type = classify(filename, media_type)
        extraction = await self._extract.execute(kind=kind, data=data)
        attachment = await self._attachments.add(
            AttachmentModel(
                team_id=team_id,
                uploaded_by=uploader.id,
                filename=filename,
                media_type=canonical_type,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                kind=kind.value,
                extracted_text=extraction.text,
                text_chars=extraction.text_chars,
                extraction_error=extraction.error,
            )
        )
        await self._attachments.put_blob(attachment.id, data)
        return attachment
