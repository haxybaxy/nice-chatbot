"""Map one graph event onto UI chunks: streamed model tokens, a landed model step, a landed tool round."""

# Library boundary: LangChain message chunks and LangGraph updates carry `Any`-typed payloads.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import cast

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.core.agent.citations import citations_in
from app.core.agent.content import ai_messages, fragments, text_of, tool_messages
from app.core.agent.events import StepCompleted, UIChunkEvent
from app.core.agent.parts import PartWriter
from app.core.agent.server_tools import server_searches
from app.core.agent.usage import RunUsage, model_name_of, usage_of
from app.core.ui_stream import ToolInputAvailableChunk


def on_message_chunk(writer: PartWriter, message: object) -> list[UIChunkEvent]:
    """A streamed chunk from a model node: text, reasoning and tool-input deltas, plus what a
    provider-executed search streams — its ``web_search_call`` block and the citations on the text."""
    if not isinstance(message, AIMessageChunk):
        return []
    out: list[UIChunkEvent] = []
    if not writer.step_open:
        out.extend(writer.open_step())
    writer.streamed_in_step = True
    for kind, text in fragments(message.content):
        out.extend(writer.delta(kind, text))
    for citation in citations_in(message.content):
        out.extend(writer.cite(citation))
    for search in server_searches(message.content):
        out.extend(writer.server_search(search))
    for call in message.tool_call_chunks:
        out.extend(_tool_call_chunk(writer, call.get("id"), call.get("name"), call.get("args"), call.get("index")))
    return out


def _tool_call_chunk(
    writer: PartWriter, call_id: str | None, name: str | None, args: str | None, index: object
) -> list[UIChunkEvent]:
    out: list[UIChunkEvent] = []
    if call_id and call_id not in writer.started_calls:
        out.extend(writer.tool_start(call_id, name or "unknown"))
        if isinstance(index, int):
            writer.calls_by_index[index] = call_id
    resolved = call_id or (writer.calls_by_index.get(index) if isinstance(index, int) else None)
    if resolved and args:
        out.append(writer.emit({"type": "tool-input-delta", "toolCallId": resolved, "inputTextDelta": args}))
    return out


def _land_model_message(writer: PartWriter, message: AIMessage) -> list[UIChunkEvent]:
    out: list[UIChunkEvent] = []
    if not writer.step_open:
        out.extend(writer.open_step())
    if not writer.streamed_in_step:  # `nostream` model, or a provider that did not stream
        out.extend(writer.landed_content(message.content))
    out.extend(writer.close_text())
    for search in server_searches(message.content):  # already announced when they streamed
        out.extend(writer.server_search(search))
    for call in message.tool_calls:
        call_id = str(call.get("id") or uuid.uuid4().hex)
        if call_id not in writer.started_calls:
            out.extend(writer.tool_start(call_id, call["name"]))
        chunk: ToolInputAvailableChunk = {
            "type": "tool-input-available",
            "toolCallId": call_id,
            "toolName": call["name"],
            "input": call["args"],
        }
        out.append(writer.emit(chunk))
    return out


def on_model_update(
    writer: PartWriter, update: Mapping[str, object], usage: RunUsage, step: int
) -> tuple[list[UIChunkEvent], StepCompleted | None, RunUsage]:
    """A model node landed its message(s): settle parts, announce tool inputs, close the step."""
    messages = ai_messages(update)
    if not messages:
        return [], None, usage
    out: list[UIChunkEvent] = []
    for message in messages:
        out.extend(_land_model_message(writer, message))
        usage = usage.add(model_name_of(message), usage_of(message))
    out.extend(writer.finish_step())
    completed = StepCompleted(kind="assistant", messages=list(messages), parts=writer.parts(), usage=usage, step=step)
    return out, completed, usage


def _tool_output(writer: PartWriter, message: ToolMessage) -> UIChunkEvent:
    artifact = cast("Mapping[str, object] | None", message.artifact if isinstance(message.artifact, Mapping) else None)
    is_error = message.status == "error" or bool(artifact and artifact.get("is_error"))
    if is_error:
        return writer.emit(
            {"type": "tool-output-error", "toolCallId": message.tool_call_id, "errorText": text_of(message)}
        )
    output = artifact.get("output") if artifact is not None else None
    if output is None:
        output = {"content": text_of(message)}
    return writer.emit({"type": "tool-output-available", "toolCallId": message.tool_call_id, "output": output})


def on_tool_update(
    writer: PartWriter, update: Mapping[str, object], usage: RunUsage, step: int
) -> tuple[list[UIChunkEvent], StepCompleted | None]:
    """The tools (or budget) node landed: one output chunk per tool result."""
    messages = tool_messages(update)
    if not messages:
        return [], None
    out = [_tool_output(writer, message) for message in messages]
    completed = StepCompleted(kind="tool", messages=list(messages), parts=writer.parts(), usage=usage, step=step)
    return out, completed
