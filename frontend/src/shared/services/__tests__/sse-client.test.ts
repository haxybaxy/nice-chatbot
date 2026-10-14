import { parseJsonEventStream, uiMessageChunkSchema, type UIMessageChunk } from "ai";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// Importing the auth service registers the refresh handler with auth-bridge, exactly as the
// app does at startup.
import "@/features/auth/services/auth.service";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { ApiError, SESSION_ENDED_MESSAGE } from "@/shared/services/api-error";
import { openEventStream } from "@/shared/services/sse-client";
import { tokenStorage } from "@/shared/services/token-storage";
import { errorResponse } from "@/test/msw/fixtures/error";
import { makeAccessToken, makeTokens } from "@/test/msw/fixtures/user";
import { server } from "@/test/msw/server";
import { controllableRunEvents, mockRunEvents, runEventsResponse, sseBody } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";
import { createFakeJWT } from "@/test/test-utils";

// The chat routes are not in the spec yet, so `GET /api/users/me` stands in: the client needs a
// `GET` spec path for its typing and nothing else, and the stream handler is a raw `http.get`.
const STREAM_PATH = API_ENDPOINTS.USERS.ME;

const chunks: UIMessageChunk[] = [
  { type: "start", messageId: "msg-1" },
  { type: "text-start", id: "t-1" },
  { type: "text-delta", id: "t-1", delta: "Hello" },
  { type: "text-end", id: "t-1" },
  { type: "finish" },
];

const expiredAccessToken = () =>
  createFakeJWT({ sub: "user-1", exp: Math.floor(Date.now() / 1000) - 60 });

async function collect<T>(stream: ReadableStream<T>): Promise<T[]> {
  const reader = stream.getReader();
  const out: T[] = [];
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return out;
    out.push(value);
  }
}

describe("openEventStream", () => {
  it("sends the bearer token and Accept header and resolves with the readable body", async () => {
    const live = makeAccessToken();
    let headers: Headers | undefined;
    server.use(
      mockRunEvents(STREAM_PATH, ({ request }) => {
        headers = request.headers;
        return runEventsResponse(chunks);
      })
    );
    tokenStorage.setTokens(makeTokens({ accessToken: live }));

    const stream = await openEventStream(STREAM_PATH, {});

    expect(headers?.get("authorization")).toBe(`Bearer ${live}`);
    expect(headers?.get("accept")).toBe("text/event-stream");
    expect(await new Response(stream).text()).toBe(sseBody(chunks));
  });

  it("refreshes before connecting when the access token is expired", async () => {
    const fresh = makeAccessToken();
    let refreshes = 0;
    const seen: string[] = [];
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () => {
        refreshes += 1;
        return HttpResponse.json(makeTokens({ accessToken: fresh, refreshToken: "rt-2" }));
      }),
      mockRunEvents(STREAM_PATH, ({ request }) => {
        seen.push(request.headers.get("authorization") ?? "none");
        return runEventsResponse(chunks);
      })
    );
    tokenStorage.setTokens(makeTokens({ accessToken: expiredAccessToken(), refreshToken: "rt-1" }));

    await openEventStream(STREAM_PATH, {});

    expect(refreshes).toBe(1);
    expect(seen).toEqual([`Bearer ${fresh}`]);
    expect(tokenStorage.getRefreshToken()).toBe("rt-2");
  });

  it("on 401 refreshes once and retries with the new token", async () => {
    const stale = makeAccessToken();
    const fresh = makeAccessToken("user-1-fresh");
    let refreshes = 0;
    const seen: string[] = [];
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () => {
        refreshes += 1;
        return HttpResponse.json(makeTokens({ accessToken: fresh, refreshToken: "rt-2" }));
      }),
      mockRunEvents(STREAM_PATH, ({ request }) => {
        const auth = request.headers.get("authorization") ?? "none";
        seen.push(auth);
        return auth === `Bearer ${fresh}`
          ? runEventsResponse(chunks)
          : errorResponse(401, "AUTH_FAILED", "Token expired");
      })
    );
    tokenStorage.setTokens(makeTokens({ accessToken: stale, refreshToken: "rt-1" }));

    const stream = await openEventStream(STREAM_PATH, {});

    expect(refreshes).toBe(1);
    expect(seen).toEqual([`Bearer ${stale}`, `Bearer ${fresh}`]);
    expect(await new Response(stream).text()).toBe(sseBody(chunks));
  });

  it("ends the session when the retry is rejected too", async () => {
    let hits = 0;
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () =>
        HttpResponse.json(makeTokens({ accessToken: makeAccessToken(), refreshToken: "rt-2" }))
      ),
      mockRunEvents(STREAM_PATH, () => {
        hits += 1;
        return errorResponse(401, "AUTH_FAILED", "Token expired");
      })
    );
    tokenStorage.setTokens(makeTokens({ refreshToken: "rt-1" }));

    const failure = await openEventStream(STREAM_PATH, {}).catch((e: unknown) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(401);
    expect((failure as ApiError).message).toBe(SESSION_ENDED_MESSAGE);
    expect(hits).toBe(2);
    expect(tokenStorage.getAccessToken()).toBeNull();
    expect(tokenStorage.getRefreshToken()).toBeNull();
  });

  it("ends the session when the refresh token is rejected", async () => {
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () =>
        errorResponse(401, "AUTH_FAILED", "Invalid or expired refresh token")
      ),
      mockRunEvents(STREAM_PATH, () => errorResponse(401, "AUTH_FAILED", "Token expired"))
    );
    tokenStorage.setTokens(makeTokens({ refreshToken: "rt-1" }));

    const failure = await openEventStream(STREAM_PATH, {}).catch((e: unknown) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(401);
    expect(tokenStorage.getRefreshToken()).toBeNull();
  });

  it("does not round-trip a refresh when there is no refresh token", async () => {
    let refreshes = 0;
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () => {
        refreshes += 1;
        return HttpResponse.json(makeTokens());
      }),
      mockRunEvents(STREAM_PATH, () => errorResponse(401, "AUTH_FAILED", "Token expired"))
    );
    tokenStorage.setTokens(makeTokens());
    localStorage.clear(); // access token in memory, refresh token gone

    const failure = await openEventStream(STREAM_PATH, {}).catch((e: unknown) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).message).toBe(SESSION_ENDED_MESSAGE);
    expect(refreshes).toBe(0);
    expect(tokenStorage.getAccessToken()).toBeNull();
  });

  it("surfaces the backend envelope on other errors", async () => {
    server.use(mockRunEvents(STREAM_PATH, () => errorResponse(403, "FORBIDDEN", "Not a member")));
    tokenStorage.setTokens(makeTokens());

    const failure = await openEventStream(STREAM_PATH, {}).catch((e: unknown) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(403);
    expect((failure as ApiError).message).toBe("Not a member");
    expect((failure as ApiError).code).toBe("FORBIDDEN");
    expect((failure as ApiError).correlationId).toBe("c-1");
    expect(tokenStorage.getRefreshToken()).not.toBeNull();
  });

  it("rejects with the abort reason when the signal is already aborted", async () => {
    let hits = 0;
    server.use(
      mockRunEvents(STREAM_PATH, () => {
        hits += 1;
        return runEventsResponse(chunks);
      })
    );
    tokenStorage.setTokens(makeTokens());
    const controller = new AbortController();
    controller.abort();

    await expect(openEventStream(STREAM_PATH, { signal: controller.signal })).rejects.toMatchObject(
      {
        name: "AbortError",
      }
    );
    expect(hits).toBe(0);
  });

  it("hands back a live stream that the test can drive and the client can cancel", async () => {
    const events = controllableRunEvents();
    server.use(mockRunEvents(STREAM_PATH, () => events.response));
    tokenStorage.setTokens(makeTokens());

    const stream = await openEventStream(STREAM_PATH, {});
    const reader = stream.getReader();
    const first: UIMessageChunk = { type: "start", messageId: "msg-1" };
    events.push(first);

    const { value } = await reader.read();
    expect(new TextDecoder().decode(value)).toBe(`id: 1\ndata: ${JSON.stringify(first)}\n\n`);

    await reader.cancel();
    await expect(events.aborted).resolves.toBeUndefined();
  });

  it("yields the chunks `sseBody` framed when parsed with the AI SDK", async () => {
    server.use(mockRunEvents(STREAM_PATH, () => runEventsResponse(chunks, { firstSeq: 7 })));
    tokenStorage.setTokens(makeTokens());

    const stream = await openEventStream(STREAM_PATH, {});
    const results = await collect(parseJsonEventStream({ stream, schema: uiMessageChunkSchema }));

    expect(results.map((result) => (result.success ? result.value : result.error))).toEqual(chunks);
  });
});
