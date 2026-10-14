"""structlog configuration and the one place loggers come from.

One pipeline renders both structlog-origin and stdlib-origin records through
``structlog.stdlib.ProcessorFormatter``: application code calls :func:`get_logger`; anything
still using ``logging.getLogger`` (uvicorn, sqlalchemy, botocore, alembic) is treated as a
"foreign" record and enriched by the same processor chain.

Convention: ``logger = get_logger(__name__)`` at module top — this module is the only one that
imports ``structlog``. Pass context as keyword arguments, never interpolate into the message
(ruff ``G``/``LOG`` enforce this). Request context (correlation id, user id) is injected
automatically.
"""

import logging.config

import structlog
from structlog.typing import EventDict, Processor

from app.core.config import settings
from app.core.context import correlation_id, request_user_id

# Third-party loggers pinned so a chatty library can't flood the output at INFO/DEBUG.
_LIBRARY_LOG_LEVELS: dict[str, str] = {
    "uvicorn.access": "WARNING",  # our middleware logs requests
    "uvicorn.error": "INFO",  # startup / shutdown messages
    "sqlalchemy.engine": "WARNING",
    "sqlalchemy.pool": "WARNING",
    "httpx": "WARNING",
    "httpcore": "WARNING",
    "botocore": "WARNING",
    "boto3": "WARNING",
    "urllib3": "WARNING",
    "alembic": "INFO",
}


def merge_request_context(_logger: object, _method_name: str, event_dict: EventDict) -> EventDict:
    """Copy the request-scoped ContextVars onto every event.

    The first parameter is ``object`` rather than structlog's ``WrappedLogger`` alias because that
    alias is literally ``Any``, which ``reportExplicitAny`` bans.
    """
    cid = correlation_id.get()
    if cid:
        event_dict.setdefault("correlation_id", cid)
    uid = request_user_id.get()
    if uid:
        event_dict.setdefault("user_id", uid)
    return event_dict


def _use_json() -> bool:
    """``auto`` renders console output only on a local machine; every deployed tier gets JSON."""
    if settings.log_format == "json":
        return True
    if settings.log_format == "console":
        return False
    return not settings.is_local


def _shared_processors(json_output: bool) -> list[Processor]:
    """Processors applied to structlog-origin AND stdlib-origin records alike."""
    processors: list[Processor] = [
        merge_request_context,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    if json_output:
        # ConsoleRenderer formats exceptions itself; JSON needs them rendered to a string field.
        processors.append(structlog.processors.format_exc_info)
    return processors


def _build_formatter() -> structlog.stdlib.ProcessorFormatter:
    json_output = _use_json()
    renderer: Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer(colors=True)
    )
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(json_output),
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )


def _logging_config() -> dict[str, object]:
    level = settings.log_level.upper()
    loggers: dict[str, dict[str, object]] = {
        name: {"level": lib_level, "handlers": ["console"], "propagate": False}
        for name, lib_level in _LIBRARY_LOG_LEVELS.items()
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": {"()": _build_formatter}},
        "handlers": {
            "console": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout", "formatter": "default"},
        },
        "loggers": loggers,
        "root": {"level": level, "handlers": ["console"]},
    }


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Module logger; call once at module top with ``__name__``.

    Thin wrapper over ``structlog.stdlib.get_logger`` so callers never import structlog directly.
    Safe to call before :func:`configure_logging` runs: ``cache_logger_on_first_use`` defers
    binding until the first log call.
    """
    return structlog.stdlib.get_logger(name)


def configure_logging() -> None:
    """Configure structlog + stdlib logging. Idempotent; call once at startup."""
    json_output = _use_json()
    structlog.configure(
        processors=[
            *_shared_processors(json_output),
            # Must be last: hands the event dict to the stdlib handler's ProcessorFormatter.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logging.config.dictConfig(_logging_config())
