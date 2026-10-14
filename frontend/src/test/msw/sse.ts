/**
 * MSW helpers for the run event stream (`GET …/runs/{run_id}/events`, `text/event-stream`).
 *
 * The backend replays a run's event log as SSE frames — `id: <seq>` (the resume cursor) and a
 * `data:` line holding one AI SDK `UIMessageChunk` — and closes with `data: [DONE]`. These
 * helpers produce exactly that framing from typed chunks, so a test script is a `UIMessageChunk[]`
 * and the parser side (`parseJsonEventStream` + `uiMessageChunkSchema`) is exercised for real.
 *
 * Stream responses register through a raw `http.get` (`mockRunEvents`) rather than `mockApi`:
 * `mockApi` types the response as the operation's JSON `*Out` schema, which an event stream is
 * not. The runtime contract validator skips `text/event-stream` responses for the same reason.
 */
import { UI_MESSAGE_STREAM_HEADERS, type UIMessageChunk } from "ai";
import {
  type DefaultBodyType,
  http,
  HttpResponse,
  type HttpHandler,
  type HttpResponseResolver,
} from "msw";

import type { ApiPath } from "@/shared/api/types";

import { url } from "./typed-http";

const encoder = new TextEncoder();
const DONE_FRAME = "data: [DONE]\n\n";

/** One frame as the backend's event log writes it. */
function frame(seq: number, chunk: UIMessageChunk): string {
  return `id: ${seq}\ndata: ${JSON.stringify(chunk)}\n\n`;
}

/** The whole body of a finished run: every chunk framed from `firstSeq`, then `[DONE]`. */
export function sseBody(chunks: UIMessageChunk[], { firstSeq = 1 }: { firstSeq?: number } = {}) {
  return chunks.map((chunk, index) => frame(firstSeq + index, chunk)).join("") + DONE_FRAME;
}

/** A complete event-stream response (the headers the AI SDK's own servers send). */
export function runEventsResponse(
  chunks: UIMessageChunk[],
  options: { firstSeq?: number } = {}
): HttpResponse<DefaultBodyType> {
  return new HttpResponse(sseBody(chunks, options), { headers: UI_MESSAGE_STREAM_HEADERS });
}

export interface ControllableRunEvents {
  /** Return this from the handler; it stays open until `end()`. */
  response: HttpResponse<DefaultBodyType>;
  /** Frame and send one chunk. */
  push(chunk: UIMessageChunk): void;
  /** Send `[DONE]` and close the stream. */
  end(): void;
  /** Resolves when the client cancels the stream (abort / transport `close()`). */
  aborted: Promise<void>;
}

/**
 * An event stream the test drives chunk by chunk — for "running" states, mid-stream aborts and
 * reconnects. Backed by a `ReadableStream` controller; `aborted` settles from its `cancel()`.
 */
export function controllableRunEvents({ firstSeq = 1 }: { firstSeq?: number } = {}) {
  let controller: ReadableStreamDefaultController<Uint8Array> | undefined;
  let markAborted = () => {};
  const aborted = new Promise<void>((resolve) => {
    markAborted = resolve;
  });
  let seq = firstSeq;

  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
    cancel() {
      markAborted();
    },
  });

  const events: ControllableRunEvents = {
    response: new HttpResponse(stream, { headers: UI_MESSAGE_STREAM_HEADERS }),
    push(chunk) {
      controller?.enqueue(encoder.encode(frame(seq++, chunk)));
    },
    end() {
      controller?.enqueue(encoder.encode(DONE_FRAME));
      controller?.close();
    },
    aborted,
  };
  return events;
}

/**
 * Register a handler for an event-stream `GET`. `path` is a spec path (today the chat routes are
 * not in the spec yet, so tests stand in another `GET`); the resolver returns
 * `runEventsResponse(...)`, a `controllableRunEvents().response` or an `errorResponse(...)`.
 */
export function mockRunEvents(path: ApiPath, resolver: HttpResponseResolver): HttpHandler {
  return http.get(url(path), resolver);
}
