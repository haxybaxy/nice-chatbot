"""Server-Sent Events framing for the AI SDK *UI Message Stream*.

The run-events endpoint streams ``app/core/ui_stream.py`` chunks as SSE: one ``data:`` line of
compact JSON per chunk, each frame carrying the run-event sequence as its ``id`` so a client that
reconnects sends ``Last-Event-ID`` and resumes where it stopped. The stream ends with
``data: [DONE]`` and keeps itself alive with comment frames while a run is idle.

``UIMessageStreamResponse`` sets the headers ``useChat``'s transport expects
(``x-vercel-ai-ui-message-stream: v1``) and the ones that stop proxies from buffering.
"""

import json
from collections.abc import AsyncIterable, Mapping
from typing import Final

from fastapi.responses import StreamingResponse

UI_MESSAGE_STREAM_HEADER: Final = "x-vercel-ai-ui-message-stream"
SSE_PING: Final = b": ping\n\n"
SSE_DONE: Final = b"data: [DONE]\n\n"


class UIMessageStreamResponse(StreamingResponse):
    """A ``text/event-stream`` response carrying UI message chunks."""

    media_type = "text/event-stream"

    def __init__(
        self, content: AsyncIterable[bytes], *, status_code: int = 200, headers: Mapping[str, str] | None = None
    ) -> None:
        merged = {
            UI_MESSAGE_STREAM_HEADER: "v1",
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            **(headers or {}),
        }
        super().__init__(content, status_code=status_code, headers=merged, media_type=self.media_type)


def encode_sse_event(seq: int, payload: object) -> bytes:
    """``id: <seq>\\ndata: <compact json>\\n\\n`` — one SSE frame per persisted run event."""
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"id: {seq}\ndata: {data}\n\n".encode()
