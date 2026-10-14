"""The UI Message Stream vocabulary: validation, the buffered sink and the parts fold."""

import asyncio
from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from app.core.ui_fold import fold_parts
from app.core.ui_stream import (
    UI_CHUNK_ADAPTER,
    BufferedEventSink,
    CancelToken,
    UIChunk,
    data_chunk,
    is_terminal,
    source_url_chunk,
)

# One canonical run: a text step, a tool round, a second text step and finish. The frontend's
# SSE fixtures mirror this sequence.
CANONICAL: list[UIChunk] = [
    {"type": "start", "messageId": "m1"},
    {"type": "start-step"},
    {"type": "text-start", "id": "t1"},
    {"type": "text-delta", "id": "t1", "delta": "Let me "},
    {"type": "text-delta", "id": "t1", "delta": "search."},
    {"type": "text-end", "id": "t1"},
    {"type": "tool-input-start", "toolCallId": "c1", "toolName": "web_search"},
    {"type": "tool-input-delta", "toolCallId": "c1", "inputTextDelta": '{"query": "py'},
    {"type": "tool-input-delta", "toolCallId": "c1", "inputTextDelta": 'thon 3.14"}'},
    {"type": "tool-input-available", "toolCallId": "c1", "toolName": "web_search", "input": {"query": "python 3.14"}},
    {"type": "finish-step"},
    {"type": "tool-output-available", "toolCallId": "c1", "output": {"results": [{"sourceId": "1"}]}},
    source_url_chunk("1", "https://docs.python.org/3.14/whatsnew/", "What's new in 3.14"),
    data_chunk("research-task", {"id": "a", "status": "running"}, id="a"),
    data_chunk("research-task", {"id": "a", "status": "done"}, id="a"),
    data_chunk("conversation-title", {"title": "Python 3.14"}, transient=True),
    {"type": "start-step"},
    {"type": "reasoning-start", "id": "r1"},
    {"type": "reasoning-delta", "id": "r1", "delta": "Summarize"},
    {"type": "reasoning-end", "id": "r1"},
    {"type": "text-start", "id": "t2"},
    {"type": "text-delta", "id": "t2", "delta": "Python 3.14 adds ... [1]"},
    {"type": "text-end", "id": "t2"},
    {"type": "finish-step"},
    {"type": "finish", "finishReason": "stop"},
]


class TestAdapter:
    def test_accepts_every_canonical_chunk(self) -> None:
        for chunk in CANONICAL:
            assert UI_CHUNK_ADAPTER.validate_python(dict(chunk)) == chunk

    def test_rejects_unknown_type_and_missing_fields(self) -> None:
        with pytest.raises(ValidationError):
            UI_CHUNK_ADAPTER.validate_python({"type": "bogus"})
        with pytest.raises(ValidationError):
            UI_CHUNK_ADAPTER.validate_python({"type": "text-delta", "id": "t"})

    def test_terminal_types(self) -> None:
        assert is_terminal({"type": "finish"})
        assert is_terminal({"type": "abort", "reason": "cancelled"})
        assert not is_terminal({"type": "finish-step"})


class TestFold:
    def test_canonical_run_folds_into_ui_parts(self) -> None:
        parts = fold_parts(CANONICAL)
        assert parts == [
            {"type": "step-start"},
            {"type": "text", "text": "Let me search.", "state": "done"},
            {
                "type": "tool-web_search",
                "toolCallId": "c1",
                "state": "output-available",
                "input": {"query": "python 3.14"},
                "output": {"results": [{"sourceId": "1"}]},
            },
            {
                "type": "source-url",
                "sourceId": "1",
                "url": "https://docs.python.org/3.14/whatsnew/",
                "title": "What's new in 3.14",
            },
            {"type": "data-research-task", "id": "a", "data": {"id": "a", "status": "done"}},
            {"type": "step-start"},
            {"type": "reasoning", "text": "Summarize", "state": "done"},
            {"type": "text", "text": "Python 3.14 adds ... [1]", "state": "done"},
        ]

    def test_interrupted_tool_input_is_settled(self) -> None:
        parts = fold_parts(CANONICAL[:9])
        tool = parts[-1]
        assert tool["state"] == "input-available"
        assert tool["input"] == {"query": "python 3.14"}

    def test_reset_step_drops_the_last_step(self) -> None:
        chunks: list[UIChunk] = [
            {"type": "start-step"},
            {"type": "text-start", "id": "a"},
            {"type": "text-delta", "id": "a", "delta": "kept"},
            {"type": "text-end", "id": "a"},
            {"type": "finish-step"},
            {"type": "start-step"},
            {"type": "text-start", "id": "b"},
            {"type": "text-delta", "id": "b", "delta": "partial"},
            {"type": "reset-step"},
            {"type": "start-step"},
            {"type": "text-start", "id": "c"},
            {"type": "text-delta", "id": "c", "delta": "retried"},
            {"type": "text-end", "id": "c"},
        ]
        assert [part.get("text", part["type"]) for part in fold_parts(chunks)] == [
            "step-start",
            "kept",
            "step-start",
            "retried",
        ]


class _Recorder:
    def __init__(self) -> None:
        self.batches: list[list[UIChunk]] = []

    async def __call__(self, batch: Sequence[UIChunk]) -> None:
        self.batches.append(list(batch))


class TestBufferedSink:
    async def test_coalesces_consecutive_deltas_and_flushes_on_demand(self) -> None:
        recorder = _Recorder()
        sink = BufferedEventSink(recorder, flush_interval_ms=10_000, max_buffered=100)
        for chunk in CANONICAL[:6]:
            await sink.emit(chunk)
        assert recorder.batches == []
        await sink.flush()
        assert recorder.batches == [
            [
                {"type": "start", "messageId": "m1"},
                {"type": "start-step"},
                {"type": "text-start", "id": "t1"},
                {"type": "text-delta", "id": "t1", "delta": "Let me search."},
                {"type": "text-end", "id": "t1"},
            ]
        ]

    async def test_different_ids_are_not_merged(self) -> None:
        recorder = _Recorder()
        sink = BufferedEventSink(recorder, flush_interval_ms=10_000)
        await sink.emit({"type": "text-delta", "id": "a", "delta": "1"})
        await sink.emit({"type": "text-delta", "id": "b", "delta": "2"})
        await sink.flush()
        assert len(recorder.batches[0]) == 2

    async def test_flushes_when_full_or_terminal(self) -> None:
        recorder = _Recorder()
        sink = BufferedEventSink(recorder, flush_interval_ms=10_000, max_buffered=2)
        await sink.emit({"type": "start-step"})
        await sink.emit({"type": "finish-step"})
        assert len(recorder.batches) == 1
        await sink.emit({"type": "finish"})
        assert recorder.batches[1] == [{"type": "finish"}]

    async def test_timer_flushes_without_further_chunks(self) -> None:
        recorder = _Recorder()
        sink = BufferedEventSink(recorder, flush_interval_ms=20)
        await sink.emit({"type": "text-delta", "id": "a", "delta": "x"})
        await asyncio.sleep(0.1)
        assert recorder.batches == [[{"type": "text-delta", "id": "a", "delta": "x"}]]


class TestCancelToken:
    async def test_request_sets_reason_once(self) -> None:
        token = CancelToken()
        assert not token.requested
        token.request("user")
        token.request("later")
        assert token.requested
        assert await token.wait() == "user"
