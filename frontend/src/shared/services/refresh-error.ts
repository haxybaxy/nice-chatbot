/**
 * Classifies failures of the token-refresh / session-restore flow so callers
 * can tell a genuine logout apart from a recoverable blip.
 *
 * Shared (not `features/auth`) because `api-client.ts` needs it on a failed 401 refresh and
 * `shared` never imports a feature (fallow boundaries).
 */

// Structural probes for whatever an auth call throws. Client-only shapes with no wire
// counterpart (they describe error OBJECTS, not response bodies), named here because inline
// `as { … }` casts are banned — that is how hand-written wire types sneak in.
interface ResponseStatusCarrier {
  response?: { status?: unknown };
}
interface StatusCarrier {
  status?: unknown;
}

/**
 * Extract an HTTP status code from whatever an auth/refresh call throws: an
 * AxiosError (the raw refresh POST — status lives at `.response.status`), an
 * ApiError (the apiClient interceptor — status at `.status`), or any error
 * object carrying a numeric `status`. Returns `undefined` when there is no HTTP
 * response at all — a network failure, CORS block, or timeout.
 *
 * Deliberately structural (no `axios.isAxiosError`) so it works even when axios
 * is mocked in tests and regardless of which layer produced the error.
 */
function getErrorStatus(error: unknown): number | undefined {
  if (error && typeof error === "object") {
    // Axios error shape: { response?: { status } }
    const response = (error as ResponseStatusCarrier).response;
    if (response && typeof response.status === "number") {
      return response.status;
    }
    // ApiError / tagged errors: { status }
    const status = (error as StatusCarrier).status;
    if (typeof status === "number") {
      return status;
    }
  }
  return undefined;
}

/**
 * A "definitive" auth failure is one where the backend actively rejected the
 * credentials / refresh token (HTTP 401 or 403). The session is genuinely
 * invalid, so clearing the stored refresh token and sending the user to login
 * is the correct response.
 *
 * Everything else — no HTTP response (network / CORS), a timeout, or a 5xx — is
 * TRANSIENT: the refresh token may still be perfectly valid and the backend was
 * just momentarily unreachable. The previous code cleared tokens on *any*
 * failure, which turned every transient blip into a permanent, destructive
 * logout (the refresh token was deleted, forcing a full re-login). Callers must
 * NOT clear tokens on a transient failure — they should retry instead.
 */
export function isDefinitiveAuthFailure(error: unknown): boolean {
  const status = getErrorStatus(error);
  return status === 401 || status === 403;
}
