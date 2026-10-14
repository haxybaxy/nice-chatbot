import type { UIMessageChunk } from "ai";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { ConversationRunTransport } from "@/features/chat/services/conversation-run-transport";
import type { ChatMessage, CreateMessageRequest, Run } from "@/features/chat/types";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { tokenStorage } from "@/shared/services/token-storage";
import { makeRun } from "@/test/msw/fixtures/chat";
import { errorResponse } from "@/test/msw/fixtures/error";
import { textRun } from "@/test/msw/fixtures/run-chunks";
import { makeTokens } from "@/test/msw/fixtures/user";
import { server } from "@/test/msw/server";
import { controllableRunEvents, mockRunEvents, runEventsResponse } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";

const CONVERSATION_ID = "conv-t";

const userMessage = (text: string): ChatMessage => ({
  id: "u-1",
  role: "user",
  parts: [{ type: "text", text }],
});

async function collect<T>(stream: ReadableStream<T>): Promise<T[]> {
  const reader = stream.getReader();
  const out: T[] = [];
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return out;
    out.push(value);
  }
}

function makeTransport(
  overrides: Partial<ConstructorParameters<typeof ConversationRunTransport>[0]> = {}
) {
  tokenStorage.setTokens(makeTokens());
  const onRunChange = vi.fn<(run: Run | null) => void>();
  const onReconnectMiss = vi.fn();
  const transport = new ConversationRunTransport({
    conversationId: CONVERSATION_ID,
    getRunOptions: () => ({ model: "m-1", mode: "chat", tools: { webSearch: true, code: false } }),
    onRunChange,
    onReconnectMiss,
    ...overrides,
  });
  return { transport, onRunChange, onReconnectMiss };
}

const sendOptions = (messages: ChatMessage[], abortSignal?: AbortSignal) => ({
  trigger: "submit-message" as const,
  chatId: CONVERSATION_ID,
  messageId: undefined,
  messages,
  abortSignal,
});

describe("ConversationRunTransport", () => {
  it("posts the last user message's text parts with the run options, then streams the run's events", async () => {
    const bodies: CreateMessageRequest[] = [];
    const streamed: string[] = [];
    const chunks = textRun();
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request, params }) => {
        bodies.push(await request.json());
        return HttpResponse.json(makeRun({ id: "run-7", conversationId: params.conversation_id }), {
          status: 201,
        });
      }),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, ({ params }) => {
        streamed.push(`${String(params["conversation_id"])}/${String(params["run_id"])}`);
        return runEventsResponse(chunks);
      })
    );
    const { transport, onRunChange } = makeTransport();

    const stream = await transport.sendMessages(
      sendOptions([
        { id: "a-0", role: "assistant", parts: [{ type: "text", text: "earlier" }] },
        userMessage("hello"),
      ])
    );
    expect(transport.run?.id).toBe("run-7");
    expect(onRunChange).toHaveBeenLastCalledWith(expect.objectContaining({ id: "run-7" }));

    expect(await collect(stream)).toEqual(chunks);
    expect(bodies).toEqual([
      {
        parts: [{ type: "text", text: "hello" }],
        model: "m-1",
        mode: "chat",
        tools: { webSearch: true, code: false },
      },
    ]);
    expect(streamed).toEqual([`${CONVERSATION_ID}/run-7`]);
    expect(transport.run).toBeNull();
    expect(onRunChange).toHaveBeenLastCalledWith(null);
  });

  it("reads the run options through `update()` at send time", async () => {
    const bodies: CreateMessageRequest[] = [];
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(makeRun({ conversationId: CONVERSATION_ID }), { status: 201 });
      })
    );
    const { transport } = makeTransport();
    transport.update({ getRunOptions: () => ({ mode: "deep_research", tools: {} }) });

    await collect(await transport.sendMessages(sendOptions([userMessage("research")])));

    expect(bodies[0]).toEqual({
      parts: [{ type: "text", text: "research" }],
      mode: "deep_research",
      tools: {},
    });
  });

  it("refuses to regenerate and refuses a thread that does not end with a user message", async () => {
    const { transport } = makeTransport();

    await expect(
      transport.sendMessages({
        ...sendOptions([userMessage("x")]),
        trigger: "regenerate-message",
      })
    ).rejects.toThrow(/not supported/);
    await expect(
      transport.sendMessages(
        sendOptions([{ id: "a", role: "assistant", parts: [{ type: "text", text: "?" }] }])
      )
    ).rejects.toThrow(/no user message/);
  });

  it("reconnects to the active run, replaying its events from the start", async () => {
    const chunks = textRun();
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.ACTIVE_RUN, () =>
        HttpResponse.json(
          makeRun({ id: "run-active", conversationId: CONVERSATION_ID, status: "running" })
        )
      ),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, ({ request }) => {
        // No `after`: a full replay.
        expect(new URL(request.url).searchParams.has("after")).toBe(false);
        return runEventsResponse(chunks);
      })
    );
    const { transport, onReconnectMiss } = makeTransport();

    const stream = await transport.reconnectToStream({ chatId: CONVERSATION_ID });

    expect(transport.resumeStreamIsReplay).toBe(true);
    expect(stream).not.toBeNull();
    expect(await collect(stream!)).toEqual(chunks);
    expect(onReconnectMiss).not.toHaveBeenCalled();
  });

  it("resolves null and reports the miss when there is no active run (404)", async () => {
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.ACTIVE_RUN, () => errorResponse(404, "NOT_FOUND", "No run"))
    );
    const { transport, onReconnectMiss, onRunChange } = makeTransport();

    await expect(transport.reconnectToStream({ chatId: CONVERSATION_ID })).resolves.toBeNull();

    expect(onReconnectMiss).toHaveBeenCalledTimes(1);
    expect(onRunChange).not.toHaveBeenCalledWith(
      expect.objectContaining({ id: expect.any(String) })
    );
  });

  it("surfaces other failures of the active-run lookup", async () => {
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.ACTIVE_RUN, () =>
        errorResponse(403, "FORBIDDEN", "Not a member")
      )
    );
    const { transport } = makeTransport();

    await expect(transport.reconnectToStream({ chatId: CONVERSATION_ID })).rejects.toThrow(
      "Not a member"
    );
  });

  it("aborts the socket when the chat's signal aborts, and `close()` aborts it too", async () => {
    const first = controllableRunEvents();
    const second = controllableRunEvents();
    let opened = 0;
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, () =>
        HttpResponse.json(makeRun({ conversationId: CONVERSATION_ID }), { status: 201 })
      ),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, (info) => {
        opened += 1;
        return (opened === 1 ? first : second).resolver(info);
      })
    );
    const { transport, onRunChange } = makeTransport();

    // 1. the chat stops → the socket goes, the run is forgotten
    const controller = new AbortController();
    await transport.sendMessages(sendOptions([userMessage("one")], controller.signal));
    const chunk: UIMessageChunk = { type: "start", messageId: "m" };
    first.push(chunk);
    controller.abort();
    await expect(first.aborted).resolves.toBeUndefined();
    expect(transport.run).toBeNull();
    expect(onRunChange).toHaveBeenLastCalledWith(null);

    // 2. the hook unmounts → close() aborts the open socket only
    await transport.sendMessages(sendOptions([userMessage("two")]));
    expect(transport.run).not.toBeNull();
    transport.close();
    await expect(second.aborted).resolves.toBeUndefined();
    expect(transport.run).toBeNull();
  });

  it("forgets the run when the stream cannot be opened", async () => {
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, () =>
        HttpResponse.json(makeRun({ conversationId: CONVERSATION_ID }), { status: 201 })
      ),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () => errorResponse(503, "SERVICE_UNAVAILABLE"))
    );
    const { transport, onRunChange } = makeTransport();

    await expect(transport.sendMessages(sendOptions([userMessage("x")]))).rejects.toMatchObject({
      status: 503,
    });

    expect(transport.run).toBeNull();
    expect(onRunChange).toHaveBeenLastCalledWith(null);
  });
});
