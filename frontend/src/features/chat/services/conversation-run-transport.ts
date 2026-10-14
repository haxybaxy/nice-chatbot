/**
 * The `useChat` transport for one conversation.
 *
 * The backend does not stream from the POST: a message is persisted and a run queued
 * (`POST …/messages` → `RunOut`), and the run's events are a separate, replayable
 * `text/event-stream` (`GET …/runs/{run_id}/events`). So:
 *
 *  - `sendMessages` posts the last user message's text parts with the composer's run options,
 *    then opens that run's events;
 *  - `reconnectToStream` asks for the active run (`null` when the backend says 404 — the
 *    response finished while the client was away; `onReconnectMiss` lets the hook refetch the
 *    persisted thread) and opens its events from sequence 0: a full replay, hence
 *    `resumeStreamIsReplay = true` so `useChat` rebuilds the assistant message from `start`
 *    (whose `messageId` is the persisted id) instead of appending a second one;
 *  - `close()` only aborts the open socket (the run keeps going on the worker); stopping a run
 *    is `useChat.stop()` + `chatService.cancelRun()`, owned by the hook.
 *
 * One socket at a time: opening a stream aborts the previous one. The chat's `abortSignal`
 * (`stop()`) is chained onto the socket; `onRunChange` reports which run is streaming and
 * `null` once its stream closed or was aborted (the banner and the stop button key off it).
 */
import {
  type ChatTransport,
  isTextUIPart,
  parseJsonEventStream,
  type UIMessageChunk,
  uiMessageChunkSchema,
} from "ai";

import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { openEventStream } from "@/shared/services/sse-client";

import { chatService } from "./chat.service";
import type { ChatMessage, CreateMessageRequest, Run, RunRequestOptions } from "../types";

export interface ConversationRunTransportOptions {
  conversationId: string;
  /** Read when a message is sent: the composer's model, mode and tool toggles. */
  getRunOptions: () => RunRequestOptions;
  /** The run whose events are streaming; `null` once that stream closed or was aborted. */
  onRunChange?: (run: Run | null) => void;
  /** A reconnect found no active run: the thread on the server is complete and newer than ours. */
  onReconnectMiss?: () => void;
}

type SendOptions = Parameters<ChatTransport<ChatMessage>["sendMessages"]>[0];
type ReconnectOptions = Parameters<ChatTransport<ChatMessage>["reconnectToStream"]>[0];
/** What `parseJsonEventStream` yields: a parsed chunk or the parse error for that frame. */
type ParsedChunk =
  ReturnType<typeof parseJsonEventStream<UIMessageChunk>> extends ReadableStream<infer T>
    ? T
    : never;

export class ConversationRunTransport implements ChatTransport<ChatMessage> {
  readonly resumeStreamIsReplay = true;

  private options: ConversationRunTransportOptions;
  private socket: AbortController | null = null;
  private activeRun: Run | null = null;

  constructor(options: ConversationRunTransportOptions) {
    this.options = options;
  }

  /** The run being streamed right now, if any. */
  get run(): Run | null {
    return this.activeRun;
  }

  /**
   * Replace callbacks without recreating the transport (which owns the socket): the hook calls
   * this after every render so the composer's latest choices are what `sendMessages` reads.
   */
  update(options: Partial<Omit<ConversationRunTransportOptions, "conversationId">>): void {
    this.options = { ...this.options, ...options };
  }

  sendMessages = async ({
    trigger,
    messages,
    abortSignal,
  }: SendOptions): Promise<ReadableStream<UIMessageChunk>> => {
    if (trigger === "regenerate-message") {
      throw new Error("Regenerating a response is not supported.");
    }
    const body: CreateMessageRequest = {
      parts: lastUserTextParts(messages),
      ...this.options.getRunOptions(),
    };
    const run = await chatService.sendMessage(this.options.conversationId, body);
    return this.openRunEvents(run, abortSignal);
  };

  reconnectToStream = async ({
    abortSignal,
  }: ReconnectOptions): Promise<ReadableStream<UIMessageChunk> | null> => {
    const run = await chatService.getActiveRun(this.options.conversationId);
    if (abortSignal?.aborted) {
      return null;
    }
    if (!run) {
      this.setRun(null);
      this.options.onReconnectMiss?.();
      return null;
    }
    return this.openRunEvents(run, abortSignal);
  };

  /** Abort the open socket, nothing else: the run continues and can be resumed. */
  close = (): void => {
    this.socket?.abort();
    this.socket = null;
  };

  private async openRunEvents(
    run: Run,
    abortSignal: AbortSignal | undefined
  ): Promise<ReadableStream<UIMessageChunk>> {
    this.close();
    const socket = new AbortController();
    this.socket = socket;
    const abortSocket = () => socket.abort();
    abortSignal?.addEventListener("abort", abortSocket, { once: true });
    const release = () => {
      abortSignal?.removeEventListener("abort", abortSocket);
      if (this.socket === socket) {
        this.socket = null;
      }
      this.setRun(null);
    };
    socket.signal.addEventListener("abort", release, { once: true });
    if (abortSignal?.aborted) {
      socket.abort();
    }
    this.setRun(run);

    let stream: ReadableStream<Uint8Array>;
    try {
      stream = await openEventStream(API_ENDPOINTS.CHAT.RUN_EVENTS, {
        path: { conversation_id: this.options.conversationId, run_id: run.id },
        signal: socket.signal,
      });
    } catch (error) {
      release();
      throw error;
    }

    return parseJsonEventStream({ stream, schema: uiMessageChunkSchema }).pipeThrough(
      new TransformStream<ParsedChunk, UIMessageChunk>({
        transform(result, controller) {
          if (!result.success) {
            throw result.error;
          }
          controller.enqueue(result.value);
        },
        flush: release,
      })
    );
  }

  private setRun(run: Run | null): void {
    if (this.activeRun === run) {
      return;
    }
    this.activeRun = run;
    this.options.onRunChange?.(run);
  }
}

/** The text parts of the message being submitted, as `TextPartIn`s. */
function lastUserTextParts(messages: readonly ChatMessage[]): CreateMessageRequest["parts"] {
  const last = messages.at(-1);
  if (!last || last.role !== "user") {
    throw new Error("There is no user message to send.");
  }
  const parts = last.parts
    .filter(isTextUIPart)
    .map(({ text }) => ({ type: "text" as const, text }));
  if (parts.length === 0) {
    throw new Error("The message has no text.");
  }
  return parts;
}
