import { describe, expect, it } from "vitest";

import type { WireMessage } from "@/features/chat/types";
import { TOOL_PART_TYPES, toChatMessage } from "@/features/chat/utils/wire-parts";
import { makeMessage } from "@/test/msw/fixtures/chat";

const assistant = (parts: WireMessage["parts"]) =>
  toChatMessage(makeMessage({ id: "m-1", role: "assistant", parts, model: "m", runId: "r-1" }));

describe("toChatMessage", () => {
  it("maps the structural parts field by field and keeps the message's provenance", () => {
    const message = assistant([
      { type: "step-start" },
      { type: "reasoning", text: "think", state: "done" },
      { type: "text", text: "answer", state: null },
      { type: "source-url", sourceId: "1", url: "https://a.example", title: null },
    ]);

    expect(message).toEqual({
      id: "m-1",
      role: "assistant",
      metadata: { createdAt: expect.any(String), model: "m", provider: undefined, runId: "r-1" },
      parts: [
        { type: "step-start" },
        { type: "reasoning", text: "think", state: "done" },
        { type: "text", text: "answer" },
        { type: "source-url", sourceId: "1", url: "https://a.example" },
      ],
    });
  });

  it("maps a persisted file part to the SDK file part, the attachment id staying inside url", () => {
    const message = toChatMessage(
      makeMessage({
        id: "m-u",
        role: "user",
        parts: [
          {
            type: "file",
            mediaType: "image/png",
            filename: "photo.png",
            url: "/api/attachments/att-1/content",
            attachmentId: "att-1",
          },
          { type: "text", text: "see", state: "done" },
        ],
      })
    );

    expect(message.parts).toEqual([
      {
        type: "file",
        mediaType: "image/png",
        filename: "photo.png",
        url: "/api/attachments/att-1/content",
      },
      { type: "text", text: "see", state: "done" },
    ]);
  });

  it("types a known tool whose payload matches its schema", () => {
    const message = assistant([
      {
        type: "tool-run_code",
        toolCallId: "c-1",
        state: "output-available",
        input: { language: "python", code: "print(1)", timeout_s: 30 },
        output: {
          stdout: "1\n",
          stderr: "",
          exitCode: 0,
          durationMs: 5,
          truncated: false,
          timedOut: false,
        },
      },
      {
        type: "tool-web_search",
        toolCallId: "c-2",
        state: "input-available",
        input: { query: "q" },
      },
      {
        type: "tool-web_fetch",
        toolCallId: "c-3",
        state: "output-error",
        input: null,
        errorText: null,
      },
    ]);

    expect(message.parts).toEqual([
      {
        type: TOOL_PART_TYPES.code,
        toolCallId: "c-1",
        state: "output-available",
        input: { language: "python", code: "print(1)", timeout_s: 30 },
        output: {
          stdout: "1\n",
          stderr: "",
          exitCode: 0,
          durationMs: 5,
          truncated: false,
          timedOut: false,
        },
      },
      {
        type: TOOL_PART_TYPES.webSearch,
        toolCallId: "c-2",
        state: "input-available",
        input: { query: "q" },
      },
      {
        type: TOOL_PART_TYPES.webFetch,
        toolCallId: "c-3",
        state: "output-error",
        input: undefined,
        errorText: "The tool failed",
      },
    ]);
  });

  it("types a built-in search and fetch — url-only hits, no number, no page text — and keeps the flag", () => {
    const search = {
      input: { query: "python 3.14 | t-strings" },
      output: {
        query: "python 3.14 | t-strings",
        results: [
          { url: "https://a.example/p", title: null, snippet: "" },
          { url: "https://b.example" },
        ],
      },
    };
    const fetch = {
      input: { url: "https://a.example/p", query: "t-strings" },
      output: {
        sourceId: null,
        url: "https://a.example/p",
        title: null,
        content: "",
        chars: 0,
        truncated: false,
      },
    };
    const message = assistant([
      {
        type: "tool-web_search",
        toolCallId: "ws_1",
        state: "output-available",
        providerExecuted: true,
        ...search,
      },
      {
        type: "tool-web_fetch",
        toolCallId: "wf_1",
        state: "output-available",
        providerExecuted: true,
        ...fetch,
      },
      {
        type: "tool-run_code",
        toolCallId: "c-1",
        state: "input-available",
        providerExecuted: null,
        input: { language: "bash", code: "ls" },
      },
    ]);

    expect(message.parts).toEqual([
      {
        type: TOOL_PART_TYPES.webSearch,
        toolCallId: "ws_1",
        providerExecuted: true,
        state: "output-available",
        ...search,
      },
      {
        type: TOOL_PART_TYPES.webFetch,
        toolCallId: "wf_1",
        providerExecuted: true,
        state: "output-available",
        ...fetch,
      },
      {
        type: TOOL_PART_TYPES.code,
        toolCallId: "c-1",
        state: "input-available",
        input: { language: "bash", code: "ls" },
      },
    ]);
    // `null` on the wire is "unset": the SDK's flag is simply absent.
    expect(message.parts[2]).not.toHaveProperty("providerExecuted");
  });

  it("still refuses a search hit without a url or a fetch without its page", () => {
    const message = assistant([
      {
        type: "tool-web_search",
        toolCallId: "ws_1",
        state: "output-available",
        input: { query: "q" },
        output: { query: "q", results: [{ title: "No address" }] },
      },
      {
        type: "tool-web_fetch",
        toolCallId: "wf_1",
        state: "output-available",
        input: { url: "https://a.example" },
        output: { sourceId: null, url: "https://a.example", content: "", truncated: false },
      },
    ]);

    expect(message.parts.map((part) => part.type)).toEqual(["dynamic-tool", "dynamic-tool"]);
  });

  it("degrades an unknown tool, or a known tool with a foreign payload, to a dynamic tool part", () => {
    const message = assistant([
      {
        type: "tool-calendar",
        toolCallId: "c-1",
        state: "output-available",
        input: { day: 1 },
        output: "ok",
      },
      {
        type: "tool-run_code",
        toolCallId: "c-2",
        state: "output-available",
        input: { nope: true },
        output: {},
      },
      {
        type: "tool-run_code",
        toolCallId: "c-3",
        state: "output-error",
        input: {},
        errorText: "boom",
      },
    ]);

    expect(message.parts).toEqual([
      {
        type: "dynamic-tool",
        toolName: "calendar",
        toolCallId: "c-1",
        state: "output-available",
        input: { day: 1 },
        output: "ok",
      },
      {
        type: "dynamic-tool",
        toolName: "run_code",
        toolCallId: "c-2",
        state: "output-available",
        input: { nope: true },
        output: {},
      },
      // An error with an unparseable input is still the known tool: the error is what matters.
      {
        type: TOOL_PART_TYPES.code,
        toolCallId: "c-3",
        state: "output-error",
        input: undefined,
        errorText: "boom",
      },
    ]);
  });

  it("keeps the data parts it can render and drops the rest", () => {
    const plan = {
      summary: "s",
      complexity: "low",
      tasks: [{ id: "t1", title: "T", objective: "o", status: "pending" }],
    };
    const message = assistant([
      { type: "data-research-plan", id: "plan", data: plan },
      {
        type: "data-research-task",
        id: "t1",
        data: { id: "t1", title: "T", status: "done", toolCalls: 2 },
      },
      {
        type: "data-research-citations",
        id: "citations",
        data: { unsupported: [], unknownNumbers: [3] },
      },
      { type: "data-refusal", data: { category: "policy" } },
      { type: "data-research-plan", id: "plan", data: { summary: 1 } },
      { type: "data-tool-progress", id: "c-1", data: { toolCallId: "c-1", status: "running" } },
      { type: "data-something-else", data: {} },
    ]);

    expect(message.parts).toEqual([
      { type: "data-research-plan", id: "plan", data: plan },
      {
        type: "data-research-task",
        id: "t1",
        data: { id: "t1", title: "T", status: "done", toolCalls: 2 },
      },
      {
        type: "data-research-citations",
        id: "citations",
        data: { unsupported: [], unknownNumbers: [3] },
      },
      { type: "data-refusal", id: undefined, data: { category: "policy" } },
    ]);
  });
});
