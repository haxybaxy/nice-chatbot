"""Stored rows → LangChain messages: verbatim replay for the same provider, neutral rebuild otherwise."""

from __future__ import annotations

from base64 import b64encode
from typing import cast
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.core.config import attachment_settings
from app.core.llm.attachments import StoredAttachment
from app.core.llm.history import NOT_EXECUTED, StoredMessage, dump_turn, text_of_parts, to_langchain
from tests.fakes_llm import GPT, LOCAL, OPUS, SONNET, scripted_openai_turn, scripted_turn
from tests.sample_files import PNG_1X1


def _user(text: str) -> StoredMessage:
    return StoredMessage(role="user", parts=[{"type": "text", "text": text}])


def _turn_with_tool() -> tuple[AIMessage, ToolMessage, AIMessage]:
    call = scripted_turn("Let me check.", reasoning="hmm", tool_calls=[("web_search", {"query": "x"})])
    result = ToolMessage(
        content="[1] result",
        tool_call_id=str(call.tool_calls[0]["id"]),
        name="web_search",
        artifact={"output": {"q": "x"}, "is_error": False},
    )
    return call, result, scripted_turn("Answer [1].")


ASSISTANT_PARTS: list[dict[str, object]] = [
    {"type": "step-start"},
    {"type": "reasoning", "text": "hmm", "state": "done"},
    {"type": "text", "text": "Let me check.", "state": "done"},
    {
        "type": "tool-web_search",
        "toolCallId": "c1",
        "state": "output-available",
        "input": {"query": "x"},
        "output": {"q": "x"},
    },
    {"type": "source-url", "sourceId": "1", "url": "https://e.x"},
    {"type": "step-start"},
    {"type": "text", "text": "Answer [1].", "state": "done"},
]


class TestSameProvider:
    def test_dump_and_load_round_trip_keeps_thinking_signatures_and_tool_results(self) -> None:
        turn = _turn_with_tool()
        dumped = dump_turn(turn)
        assert [cast("list[str]", item["id"])[-1] for item in dumped] == ["AIMessage", "ToolMessage", "AIMessage"]
        row = StoredMessage(
            role="assistant",
            parts=ASSISTANT_PARTS,
            provider="anthropic",
            model="claude-opus-5-5",
            provider_messages=dumped,
        )
        restored = to_langchain([_user("q"), row], target=OPUS)
        assert isinstance(restored[0], HumanMessage)
        assert restored[0].content == "q"
        assert isinstance(restored[1], AIMessage)
        assert restored[1].content == turn[0].content  # thinking block + signature intact
        assert restored[1].tool_calls == turn[0].tool_calls
        assert restored[1].response_metadata["stop_reason"] == "tool_use"
        assert isinstance(restored[2], ToolMessage)
        assert restored[2].artifact == {"output": {"q": "x"}, "is_error": False}
        assert isinstance(restored[3], AIMessage)
        assert restored[3].text == "Answer [1]."

    def test_replay_is_verbatim_across_claude_models(self) -> None:
        row = StoredMessage(
            role="assistant",
            parts=ASSISTANT_PARTS,
            provider="anthropic",
            model="claude-opus-5-5",
            provider_messages=dump_turn(_turn_with_tool()),
        )
        restored = to_langchain([_user("q"), row], target=SONNET)
        assert isinstance(restored[1], AIMessage)
        first_block = restored[1].content[0]
        assert isinstance(first_block, dict)
        assert first_block["type"] == "thinking"

    def test_dangling_tool_calls_get_a_synthetic_error_result(self) -> None:
        cut_off = scripted_turn("partial", tool_calls=[("web_search", {"query": "x"})], stop_reason="max_tokens")
        row = StoredMessage(
            role="assistant", parts=[], provider="anthropic", model="m", provider_messages=dump_turn([cut_off])
        )
        restored = to_langchain([_user("q"), row, _user("go on")], target=OPUS)
        assert [type(message).__name__ for message in restored] == [
            "HumanMessage",
            "AIMessage",
            "ToolMessage",
            "HumanMessage",
        ]
        assert isinstance(restored[2], ToolMessage)
        assert (restored[2].content, restored[2].status, restored[2].tool_call_id) == (
            NOT_EXECUTED,
            "error",
            cut_off.tool_calls[0]["id"],
        )


class TestCrossProvider:
    def test_rebuilds_neutral_messages_from_parts_without_reasoning(self) -> None:
        row = StoredMessage(
            role="assistant",
            parts=ASSISTANT_PARTS,
            provider="anthropic",
            model="claude-opus-5-5",
            provider_messages=dump_turn(_turn_with_tool()),
        )
        restored = to_langchain([_user("q"), row], target=LOCAL)
        assert [type(message).__name__ for message in restored] == [
            "HumanMessage",
            "AIMessage",
            "ToolMessage",
            "AIMessage",
        ]
        step_1 = restored[1]
        assert isinstance(step_1, AIMessage)
        assert step_1.content == "Let me check."
        assert step_1.tool_calls == [{"name": "web_search", "args": {"query": "x"}, "id": "c1", "type": "tool_call"}]
        result = restored[2]
        assert isinstance(result, ToolMessage)
        assert (result.tool_call_id, result.name, result.content) == ("c1", "web_search", '{"q": "x"}')
        assert isinstance(restored[3], AIMessage)
        assert restored[3].content == "Answer [1]."

    def test_rebuild_handles_errors_and_unexecuted_calls(self) -> None:
        parts: list[dict[str, object]] = [
            {"type": "step-start"},
            {
                "type": "tool-run_code",
                "toolCallId": "a",
                "state": "output-error",
                "input": {"code": "1/0"},
                "errorText": "boom",
            },
            {"type": "tool-web_fetch", "toolCallId": "b", "state": "input-available", "input": {"url": "https://e.x"}},
        ]
        row = StoredMessage(role="assistant", parts=parts, provider="openai", model="llama", provider_messages=None)
        restored = to_langchain([row], target=OPUS)
        assert isinstance(restored[0], AIMessage)
        assert [call["id"] for call in restored[0].tool_calls] == ["a", "b"]
        results = restored[1:]
        assert all(isinstance(message, ToolMessage) and message.status == "error" for message in results)
        assert [str(message.content) for message in results] == ["boom", NOT_EXECUTED]

    def test_missing_provider_messages_falls_back_to_parts(self) -> None:
        row = StoredMessage(
            role="assistant",
            parts=[{"type": "text", "text": "plain", "state": "done"}],
            provider="anthropic",
            model="m",
        )
        restored = to_langchain([row], target=OPUS)
        assert isinstance(restored[0], AIMessage)
        assert restored[0].content == "plain"


class TestProviderExecuted:
    """A built-in search lives inside the model's message: replayed verbatim to OpenAI minus the fields
    the API only ever returns, and skipped by the neutral rebuild (its text carries the citations)."""

    def test_openai_replay_strips_the_consulted_pages_but_keeps_the_search_and_citations(self) -> None:
        turn = scripted_openai_turn(
            "Answer ([Docs](https://d.x/?utm_source=chatgpt.com)).",
            searches=[("q", ["https://d.x/", "https://e.x/"])],
            citations=[("https://d.x/?utm_source=chatgpt.com", "Docs", 7, 52)],
        )
        row = StoredMessage(
            role="assistant", parts=[], provider="openai", model=GPT.id, provider_messages=dump_turn([turn])
        )
        [replayed] = to_langchain([_user("q"), row], GPT)[1:]
        assert isinstance(replayed, AIMessage)
        blocks = cast("list[dict[str, object]]", replayed.content)
        search = next(block for block in blocks if block.get("type") == "web_search_call")
        assert search["action"] == {"type": "search", "queries": ["q"], "query": "q"}
        text = next(block for block in blocks if block.get("type") == "text")
        assert cast("list[dict[str, object]]", text["annotations"])[0]["url"] == "https://d.x/?utm_source=chatgpt.com"
        # The stored row is untouched.
        stored = cast("dict[str, object]", cast("list[dict[str, object]]", row.provider_messages)[0]["kwargs"])
        stored_blocks = cast("list[dict[str, object]]", stored["content"])
        assert "sources" in cast("dict[str, object]", stored_blocks[0]["action"])

    def test_the_neutral_rebuild_skips_provider_executed_tool_parts(self) -> None:
        parts: list[dict[str, object]] = [
            {"type": "step-start"},
            {
                "type": "tool-web_search",
                "toolCallId": "ws_1",
                "state": "output-available",
                "input": {"query": "q"},
                "output": {"query": "q", "results": []},
                "providerExecuted": True,
            },
            {"type": "text", "text": "Answer [1].", "state": "done"},
            {"type": "source-url", "sourceId": "1", "url": "https://d.x/"},
        ]
        row = StoredMessage(role="assistant", parts=parts, provider="openai", model=GPT.id, provider_messages=None)
        messages = to_langchain([_user("q"), row], OPUS)
        assert [type(message).__name__ for message in messages] == ["HumanMessage", "AIMessage"]
        answer = messages[1]
        assert isinstance(answer, AIMessage)
        assert (answer.content, answer.tool_calls) == ("Answer [1].", [])


class TestUserRows:
    def test_text_parts_are_joined_and_empty_rows_skipped(self) -> None:
        row = StoredMessage(role="user", parts=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
        assert text_of_parts(row.parts) == "a\n\nb"
        restored = to_langchain([row, StoredMessage(role="user", parts=[])], target=OPUS)
        assert len(restored) == 1
        assert restored[0].content == "a\n\nb"


# ── Attachments ──────────────────────────────────────────────────────────────


def _attachment(
    filename: str = "notes.txt",
    *,
    text: str | None = "hello",
    text_chars: int | None = None,
    error: str | None = None,
    kind: str = "text",
    media_type: str = "text/plain",
    image_bytes: bytes | None = None,
) -> StoredAttachment:
    return StoredAttachment(
        attachment_id=uuid4(),
        filename=filename,
        media_type=media_type,
        kind=kind,
        size_bytes=len(text or ""),
        text=text,
        text_chars=text_chars if text_chars is not None else (len(text) if text is not None else None),
        extraction_error=error,
        image_bytes=image_bytes,
    )


def _user_with(text: str, *attachments: StoredAttachment) -> StoredMessage:
    parts: list[dict[str, object]] = [{"type": "text", "text": text}] if text else []
    return StoredMessage(role="user", parts=parts, attachments=attachments)


def _content(message: object) -> list[dict[str, object]]:
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, list)
    return cast("list[dict[str, object]]", message.content)


class TestAttachments:
    def test_text_files_become_attachment_blocks_after_the_users_text(self) -> None:
        [human] = to_langchain([_user_with("Read it", _attachment("a.txt", text="line 1\nline 2"))], target=OPUS)

        assert _content(human) == [
            {"type": "text", "text": "Read it"},
            {
                "type": "text",
                "text": '<attachment name="a.txt" type="text/plain" chars="13">\nline 1\nline 2\n</attachment>',
            },
        ]

    def test_images_are_image_blocks_for_vision_models_and_placeholders_otherwise(self) -> None:
        image = _attachment("pic.png", text=None, kind="image", media_type="image/png", image_bytes=PNG_1X1)
        rows = [_user_with("", image)]

        [seen] = to_langchain(rows, target=OPUS)
        [blind] = to_langchain(rows, target=LOCAL)

        [block] = _content(seen)
        assert (block["type"], block["mime_type"], block["base64"]) == (
            "image",
            "image/png",
            b64encode(PNG_1X1).decode(),
        )
        assert _content(blind) == [
            {"type": "text", "text": "[image attached: pic.png — this model cannot view images]"}
        ]

    def test_an_unreadable_file_is_an_empty_tag_with_the_reason(self) -> None:
        broken = _attachment("scan.pdf", text=None, error="Encrypted PDF", kind="pdf", media_type="application/pdf")

        [human] = to_langchain([_user_with("?", broken)], target=OPUS)

        assert _content(human)[1] == {
            "type": "text",
            "text": '<attachment name="scan.pdf" type="application/pdf" unreadable="Encrypted PDF"/>',
        }

    def test_the_turn_budget_goes_to_the_latest_attachments_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(attachment_settings, "attachment_model_text_chars", 20)
        older = _user_with("first", _attachment("old.txt", text="0123456789ABCDE"))  # 15 chars
        newer = _user_with("second", _attachment("new.txt", text="abcdefghijklmno"))  # 15 chars

        first, second = to_langchain([older, newer], target=OPUS)

        assert (
            _content(second)[1]["text"]
            == '<attachment name="new.txt" type="text/plain" chars="15">\nabcdefghijklmno\n</attachment>'
        )
        assert _content(first)[1]["text"] == (
            '<attachment name="old.txt" type="text/plain" chars="15">\n01234\n[truncated: 10 more characters]\n</attachment>'
        )

    def test_text_capped_at_upload_reports_the_full_count(self) -> None:
        capped = _attachment("big.csv", text="kept", text_chars=1_000_000, media_type="text/csv")

        [human] = to_langchain([_user_with("", capped)], target=OPUS)

        assert _content(human) == [
            {
                "type": "text",
                "text": '<attachment name="big.csv" type="text/csv" chars="1000000">\nkept\n[truncated: 999996 more characters]\n</attachment>',
            }
        ]

    def test_names_are_escaped_and_rows_without_attachments_stay_strings(self) -> None:
        quoted = _attachment('say "hi" <now>.txt', text="x")

        plain, with_file = to_langchain([_user("plain"), _user_with("q", quoted)], target=OPUS)

        assert isinstance(plain, HumanMessage)
        assert plain.content == "plain"
        assert 'name="say &quot;hi&quot; &lt;now&gt;.txt"' in str(_content(with_file)[1]["text"])
