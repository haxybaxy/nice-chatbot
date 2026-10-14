/**
 * The error every transport throws. `apiClient` raises it from axios failures and the SSE client
 * (`sse-client.ts`) from non-2xx `fetch` responses, so a caller branching on `status` / `code`
 * never has to know which transport a request went through. `api-client.ts` re-exports
 * `ApiError` for the existing import sites.
 */
import type { Schema } from "../api/types";

type ErrorEnvelope = Schema<"ErrorOut">;

/**
 * Runtime check that `unknown` response data is the backend's error envelope. The key names are
 * taken from the generated type, so renaming a field on the backend fails `tsc` here.
 */
function isErrorEnvelope(data: unknown): data is ErrorEnvelope {
  if (typeof data !== "object" || data === null) {
    return false;
  }
  const candidate = data as Record<keyof ErrorEnvelope, unknown>;
  return (
    typeof candidate.error === "string" &&
    typeof candidate.code === "string" &&
    typeof candidate.statusCode === "number" &&
    typeof candidate.correlationId === "string"
  );
}

/** Best-effort message from a NON-envelope body (a proxy or CDN error page). */
function readFallbackMessage(data: unknown): string | undefined {
  if (typeof data !== "object" || data === null) {
    return undefined;
  }
  for (const key of ["error", "message"]) {
    const value = (data as Record<string, unknown>)[key];
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }
  return undefined;
}

/**
 * Error carrying the HTTP status plus the backend's error envelope (`ErrorOut`), thrown by the
 * transports in place of a vanilla `Error`. Callers that need to branch on status
 * (404 / 409 / 400) can read it directly; the global react-query retry config in
 * `providers/query-provider.tsx` keys off `"status" in error` for the 4xx-no-retry check.
 *
 * `detail`, `code` and `correlationId` come from the envelope
 * (`{error, code, statusCode, correlationId, details?}`). All are present on every backend error
 * response, but stay optional here because an ApiError can also be raised client-side (the
 * session-ended 401), where there is no envelope to read them from. `code` is the generated
 * `ErrorCode` union; at runtime it is only checked to be a string — the OpenAPI snapshot guards
 * are what keep the union honest.
 */
export class ApiError extends Error {
  readonly status: number;
  /** The backend's `error` message, when the response carried an envelope. */
  readonly detail: string | undefined;
  /** Machine-readable cause (`ErrorOut.code`). Prefer branching on this over parsing `message`. */
  readonly code: ErrorEnvelope["code"] | undefined;
  /** The id to quote in a bug report — ties this failure to a backend trace. */
  readonly correlationId: ErrorEnvelope["correlationId"] | undefined;

  constructor(
    status: number,
    message: string,
    envelope?: { detail?: string; code?: ErrorEnvelope["code"]; correlationId?: string }
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = envelope?.detail;
    this.code = envelope?.code;
    this.correlationId = envelope?.correlationId;
  }
}

/** What the user sees when the refresh token is gone or rejected; the transports throw it as a 401. */
export const SESSION_ENDED_MESSAGE = "Your session has ended. Please sign in again.";

/**
 * Translate a non-2xx response (status + parsed body, if any) into an `ApiError`. The backend
 * wraps every error in one envelope, so its `error` is the message to show; a bare
 * `error`/`message` string is kept as a fallback for non-envelope responses (a proxy, a CDN).
 */
export function apiErrorFromResponse(status: number, data: unknown): ApiError {
  const envelope = isErrorEnvelope(data) ? data : undefined;
  const detail = envelope?.error ?? readFallbackMessage(data);
  const message =
    status >= 500
      ? "Server error. Please try again later."
      : (detail ?? `Request failed (${status})`);
  return new ApiError(status, message, {
    detail,
    code: envelope?.code,
    correlationId: envelope?.correlationId,
  });
}
