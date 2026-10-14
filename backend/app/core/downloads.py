"""The binary download response for attachment content.

``AttachmentContentResponse`` is the second non-JSON success response (the first is the SSE run
event stream in ``app/core/sse.py``): the stored bytes under the attachment's own media type,
with the headers a browser needs to show or save the file safely — ``Content-Disposition``
(``inline`` by default, ``attachment`` for an explicit download; the filename RFC 6266 / 5987
encoded so any Unicode name survives), a private one-hour cache, and ``nosniff`` so a text or SVG
upload is never promoted to something executable. The class-level ``media_type`` is the generic
binary type the route is registered with (``tests/guards/test_routes.py`` exempts such routes from
the ``response_model`` rule); the actual type is set per instance.
"""

from collections.abc import AsyncIterator
from urllib.parse import quote

from fastapi.responses import StreamingResponse


async def _one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


class AttachmentContentResponse(StreamingResponse):
    """The bytes of one attachment, served as ``media_type`` under ``filename``."""

    media_type = "application/octet-stream"

    def __init__(
        self, data: bytes, *, media_type: str, filename: str, download: bool = False, status_code: int = 200
    ) -> None:
        # `status_code` is what FastAPI reads off the signature to document the success response.
        disposition = "attachment" if download else "inline"
        headers = {
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename, safe='')}",
            "Content-Length": str(len(data)),
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        }
        super().__init__(_one_chunk(data), status_code=status_code, headers=headers, media_type=media_type)
