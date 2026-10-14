/**
 * Indirection between low-level transport (API client, SSE client) and the
 * auth service so the transport modules don't import the auth service directly.
 * Without this, api-client and auth.service form an import cycle that defeats
 * tree-shaking and risks initialization-order bugs. The auth service registers
 * its refresh handler at module load time; transports call refreshAuthToken()
 * when they encounter a 401 or expired access token.
 */

let refreshHandler: (() => Promise<void>) | null = null;

export function setAuthRefreshHandler(handler: () => Promise<void>): void {
  refreshHandler = handler;
}

export async function refreshAuthToken(): Promise<void> {
  if (!refreshHandler) {
    throw new Error("Auth refresh handler is not registered");
  }
  await refreshHandler();
}
