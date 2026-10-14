"""Request middleware: correlation id + structured access log.

Pure ASGI (not ``BaseHTTPMiddleware``) so streaming responses are never buffered.

Per HTTP request: honours an incoming ``X-Request-ID`` (if it is a UUID) or generates one,
activates it as the correlation id for all downstream logging, echoes it back as
``X-Correlation-ID``, and logs one ``request completed`` line with method / path / status /
duration. Health probes and CORS preflight are not logged.
"""

import time
from uuid import UUID

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import new_correlation_id, set_correlation_id
from app.core.logging_config import get_logger

logger = get_logger(__name__)

_SKIP_LOG_PATHS = frozenset({"/api/health", "/api/health/ready"})
_SLOW_REQUEST_MS = 5_000.0


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cid = _resolve_correlation_id(scope)
        set_correlation_id(cid)

        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        status_code = 0
        correlation_header = (b"x-correlation-id", cid.encode("latin-1"))

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 0))
                headers = list(message.get("headers", []))
                headers.append(correlation_header)
                message["headers"] = headers
            await send(message)

        if method == "OPTIONS" or path in _SKIP_LOG_PATHS:
            await self.app(scope, receive, send_wrapper)
            return

        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            _log_request(method=method, path=path, status_code=status_code, duration_ms=duration_ms)


def _resolve_correlation_id(scope: Scope) -> str:
    """Use the client's ``X-Request-ID`` when it is a UUID; otherwise mint a fresh one."""
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            try:
                return str(UUID(value.decode("latin-1")))
            except ValueError:
                break
    return new_correlation_id()


def _log_request(*, method: str, path: str, status_code: int, duration_ms: float) -> None:
    if status_code >= 500:
        logger.error("request completed", method=method, path=path, status_code=status_code, duration_ms=duration_ms)
    elif status_code >= 400 or duration_ms > _SLOW_REQUEST_MS:
        logger.warning("request completed", method=method, path=path, status_code=status_code, duration_ms=duration_ms)
    else:
        logger.info("request completed", method=method, path=path, status_code=status_code, duration_ms=duration_ms)
