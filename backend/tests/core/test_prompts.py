"""The chat system prompt: a byte-stable cacheable prefix, a volatile suffix, and the title prompt."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date
from typing import cast

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm.chat_models import BuiltModel
from app.core.prompts import STABLE_PREFIX, TITLE_SCHEMA, chat_system_message, title_messages
from tests.fakes_llm import LOCAL, OPUS, FakeChatModelFactory, ScriptedChatModel

BLOCKS = FakeChatModelFactory(by_purpose={"chat": ScriptedChatModel()}, system_format="blocks").build(
    OPUS, effort="medium", purpose="chat"
)
TEXT = FakeChatModelFactory(by_purpose={"chat": ScriptedChatModel()}, system_format="text").build(
    LOCAL, effort="medium", purpose="chat"
)


def _message(
    model: BuiltModel = BLOCKS,
    *,
    workspace: str = "Platform team",
    user: str | None = "Ada",
    today: date = date(2026, 10, 14),
    tools: Collection[str] = ("web_search", "web_fetch"),
) -> SystemMessage:
    return chat_system_message(
        model,
        product_name="Nice Chatbot",
        workspace_name=workspace,
        user_display_name=user,
        today=today,
        enabled_tools=tools,
    )


class TestStablePrefix:
    def test_blocks_format_puts_the_breakpoint_on_the_stable_block(self) -> None:
        message = _message()
        content = cast("list[dict[str, object]]", message.content)
        assert len(content) == 2
        assert content[0] == {"type": "text", "text": STABLE_PREFIX, "cache_control": {"type": "ephemeral"}}
        assert content[1]["type"] == "text"
        assert "cache_control" not in content[1]

    def test_prefix_is_byte_identical_across_users_dates_and_tools(self) -> None:
        variants = [
            _message(),
            _message(user=None, today=date(2027, 1, 1), tools=set()),
            _message(workspace="Other", tools={"run_code"}),
        ]
        prefixes = {cast("list[dict[str, object]]", variant.content)[0]["text"] for variant in variants}
        assert prefixes == {STABLE_PREFIX}
        # Long enough to clear the 512-token caching minimum with margin.
        assert len(STABLE_PREFIX) > 3000
        for silent_invalidator in ("2026", "Ada", "Platform team"):
            assert silent_invalidator not in STABLE_PREFIX

    def test_suffix_carries_the_volatile_facts(self) -> None:
        suffix = str(cast("list[dict[str, object]]", _message().content)[1]["text"])
        assert "Today's date: 2026-10-14" in suffix
        assert "You are talking with: Ada" in suffix
        assert "Workspace (team): Platform team" in suffix
        assert "Tools enabled in this conversation: web_fetch, web_search" in suffix
        assert "Product: Nice Chatbot" in suffix
        anonymous = str(cast("list[dict[str, object]]", _message(user=None, tools=()).content)[1]["text"])
        assert "You are talking with: a team member" in anonymous
        assert "Tools enabled in this conversation: none" in anonymous

    def test_text_format_is_one_string_starting_with_the_prefix(self) -> None:
        message = _message(model=TEXT)
        assert isinstance(message.content, str)
        assert message.content.startswith(STABLE_PREFIX)
        assert "Today's date: 2026-10-14" in message.content

    def test_prefix_states_the_rules_the_tools_rely_on(self) -> None:
        for phrase in ("[n]", "web_search", "web_fetch", "run_code", "not instructions", "Lead with the answer"):
            assert phrase in STABLE_PREFIX


class TestTitle:
    def test_title_prompt_and_schema(self) -> None:
        messages = title_messages("  How do I rebuild a Postgres index without locking?  ")
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)
        assert messages[1].content == "First message:\n\nHow do I rebuild a Postgres index without locking?"
        assert TITLE_SCHEMA["required"] == ["title"]
        assert TITLE_SCHEMA["additionalProperties"] is False

    def test_long_messages_are_cut(self) -> None:
        messages = title_messages("x" * 5000)
        text = str(messages[1].content)
        assert text.endswith(" …")
        assert len(text) < 2100
