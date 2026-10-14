"""Stored rows → LangChain messages: verbatim replay for the same provider, neutral rebuild otherwise."""

from __future__ import annotations

from typing import cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.core.llm.history import NOT_EXECUTED, StoredMessage, dump_turn, text_of_parts, to_langchain
from tests.fakes_llm import LOCAL, OPUS, SONNET, scripted_turn


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


class TestUserRows:
    def test_text_parts_are_joined_and_empty_rows_skipped(self) -> None:
        row = StoredMessage(role="user", parts=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
        assert text_of_parts(row.parts) == "a\n\nb"
        restored = to_langchain([row, StoredMessage(role="user", parts=[])], target=OPUS)
        assert len(restored) == 1
        assert restored[0].content == "a\n\nb"
