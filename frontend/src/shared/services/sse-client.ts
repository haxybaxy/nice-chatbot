/**
 * The event-stream client — the one place besides `apiClient` that talks HTTP, and the one
 * sanctioned `fetch` (ESLint `no-restricted-globals` is off for this file only).
 *
 * `apiClient` is axios + JSON; a `text/event-stream` response needs a readable body instead, so
 * this module opens the connection with the same path typing (`API_ENDPOINTS` path + `path` /
 * `query` options from the generated spec), the same bearer / refresh rules and the same
 * `ApiError`, and hands the raw byte stream to the caller (the chat transport parses it with
 * the AI SDK's `parseJsonEventStream` + `uiMessageChunkSchema`).
 *
 * Auth, mirroring `api-client.ts`:
 *  - a pre-emptive refresh when the access token is expired and a refresh token exists (a
 *    stream that 401s after a reload is a wasted round-trip);
 *  - on 401, one refresh through `auth-bridge` (the auth service single-flights it, so a
 *    concurrent axios refresh shares the same request) and one retry; a second 401, or a
 *    definitive refresh rejection, clears the tokens and throws `ApiError(401, SESSION_ENDED)`;
 *    a transient refresh failure (network, 5xx) is rethrown as-is so the caller can retry
 *    without losing the session;
 *  - any other non-2xx is an `ApiError` built from the backend's envelope.
 */

import { ApiError, SESSION_ENDED_MESSAGE, apiErrorFromResponse } from "./api-error";
import { refreshAuthToken } from "./auth-bridge";
import { isDefinitiveAuthFailure } from "./refresh-error";
import { tokenStorage } from "./token-storage";
import {
  type PathOption,
  type QueryOption,
  type RuntimeRequestOptions,
  substitutePathParams,
} from "../api/request-options";
import type { PathsWith } from "../api/types";
import { API_ENDPOINTS } from "../config/api-endpoints";

/** `path` / `query` as the spec declares them for `GET P`, plus the abort signal. */
export type EventStreamOptions<P extends PathsWith<"get">> = {
  /** Aborting it cancels the request (or the open stream). */
  signal?: AbortSignal;
} & PathOption<P, "get"> &
  QueryOption<P, "get">;

/** The type-erased view `openStream()` works with. */
interface RuntimeStreamOptions extends RuntimeRequestOptions {
  signal?: AbortSignal;
}

/**
 * Open `GET P` as an event stream and resolve with its body once the headers say 2xx.
 *
 *   const stream = await openEventStream(API_ENDPOINTS.CHAT.RUN_EVENTS, {
 *     path: { conversation_id, run_id },
 *     signal,
 *   });
 *
 * Rejects with `ApiError` (status + envelope, or 401 + `SESSION_ENDED_MESSAGE`), with the
 * `AbortError` of an aborted signal, or with the transport's own error on a network failure.
 */
export async function openEventStream<P extends PathsWith<"get">>(
  path: P,
  options: EventStreamOptions<P>
): Promise<ReadableStream<Uint8Array>> {
  return openStream(path, options);
}

async function openStream(
  path: string,
  options: RuntimeStreamOptions
): Promise<ReadableStream<Uint8Array>> {
  const url = buildUrl(path, options);

  if (tokenStorage.isAccessTokenExpired() && tokenStorage.getRefreshToken()) {
    await refreshOrEndSession();
  }

  let response = await request(url, options.signal);

  if (response.status === 401) {
    // Nothing to refresh with: the session is over, no round-trip needed.
    if (!tokenStorage.getRefreshToken()) {
      throw endSession();
    }
    await refreshOrEndSession();
    response = await request(url, options.signal);
    if (response.status === 401) {
      throw endSession();
    }
  }

  if (!response.ok) {
    throw await toApiError(response);
  }
  if (!response.body) {
    throw new Error(`Event stream ${path} has no response body`);
  }
  return response.body;
}

function request(url: string, signal: AbortSignal | undefined): Promise<Response> {
  const headers = new Headers({ Accept: "text/event-stream" });
  const accessToken = tokenStorage.getAccessToken();
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  return fetch(url, { method: "GET", headers, signal, cache: "no-store" });
}

/**
 * Refresh through the auth service. A definitive rejection (401/403) — or a refresh that
 * produced no access token — ends the session; a transient failure is rethrown unchanged.
 */
async function refreshOrEndSession(): Promise<void> {
  try {
    await refreshAuthToken();
  } catch (error) {
    if (isDefinitiveAuthFailure(error)) {
      throw endSession();
    }
    throw error;
  }
  if (!tokenStorage.getAccessToken()) {
    throw endSession();
  }
}

/** Forget the tokens and build the error the caller surfaces as "signed out". */
function endSession(): ApiError {
  tokenStorage.clearTokens();
  return new ApiError(401, SESSION_ENDED_MESSAGE);
}

async function toApiError(response: Response): Promise<ApiError> {
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    data = undefined; // no body, or not JSON (a proxy page) — the status alone names the error
  }
  return apiErrorFromResponse(response.status, data);
}

/**
 * Base URL + substituted path + query string. Query values are appended one `key=value` pair
 * per item (arrays repeat the key, which is how FastAPI reads list parameters); `undefined` and
 * `null` are skipped like axios does.
 */
function buildUrl(path: string, options: RuntimeRequestOptions): string {
  const url = `${API_ENDPOINTS.EXTERNAL.BACKEND}${substitutePathParams(path, options.path)}`;
  if (!options.query) {
    return url;
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options.query)) {
    if (value === undefined || value === null) continue;
    for (const item of Array.isArray(value) ? value : [value]) {
      params.append(key, String(item));
    }
  }
  const search = params.toString();
  return search ? `${url}?${search}` : url;
}
