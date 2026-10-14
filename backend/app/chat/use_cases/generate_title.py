from app.core.llm.catalog import model_catalog
from app.core.llm.chat_models import ChatModelFactory
from app.core.logging_config import get_logger
from app.core.prompts import TITLE_SCHEMA, title_messages
from app.core.research.prompts import parse_json_object

logger = get_logger(__name__)

TITLE_MAX_CHARS = 80
_FALLBACK_TITLE = "New conversation"


def _fallback_title(text: str) -> str:
    """The first non-empty line of the user's message, clipped — what the UI shows when no model answers."""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return _clip(first_line) or _FALLBACK_TITLE


def _clip(title: str) -> str:
    title = " ".join(title.split())
    if len(title) <= TITLE_MAX_CHARS:
        return title
    return title[: TITLE_MAX_CHARS - 1].rstrip() + "…"


class GenerateTitle:
    """Name a conversation from its first user message with the cheap title model (structured
    output, low effort, no streaming). Total: any failure — provider, parsing, an empty title —
    falls back to the message's first line, so a title never fails or delays a run for long."""

    def __init__(self, llm: ChatModelFactory) -> None:
        self._llm = llm

    async def execute(self, *, text: str) -> str:
        try:
            built = self._llm.build(
                model_catalog().title_model(),
                effort="low",
                purpose="title",
                max_tokens=512,
                output_schema=TITLE_SCHEMA,
                silent=True,
            )
            response = await built.runnable().ainvoke(title_messages(text))
            payload = parse_json_object(response.text) or {}
            title = payload.get("title")
        except Exception as error:  # noqa: BLE001 — a title must never fail the run; the first line will do
            logger.warning("conversation title generation failed", error_type=type(error).__name__)
            return _fallback_title(text)
        if not isinstance(title, str) or not title.strip():
            return _fallback_title(text)
        return _clip(title.strip())
