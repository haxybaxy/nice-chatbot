import axios, { type AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from "axios";

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
import type { BodylessPaths, HttpMethod, PathsWith, RequestBody, SuccessBody } from "../api/types";
import { API_ENDPOINTS } from "../config/api-endpoints";

// `ApiError` lives in ./api-error (shared with the SSE client); re-exported for the import sites
// that know it as the client's error.
export { ApiError } from "./api-error";

// ── Path-typed call signatures ───────────────────────────────────────────────────────────────
//
// `apiClient.get(path)`, `.post(path, body)`, … take a spec path (`API_ENDPOINTS.*`) and derive
// the body, path/query params and result from the generated OpenAPI types. There is no free type
// parameter, so a hand-written wire shape cannot be passed in or asserted out. `PathOption` /
// `QueryOption` are shared with the SSE client (`../api/request-options`).

type RequestOptions<P extends PathsWith<M>, M extends HttpMethod> = {
  /** Skip the Authorization header and the auto-refresh on 401 (public endpoints). */
  skipAuth?: boolean;
} & PathOption<P, M> &
  QueryOption<P, M>;

/**
 * `[options]` when the operation needs path/query input, `[options?]` otherwise. Distributive
 * over `P` so a wrong-verb call reports "not assignable to BodylessPaths<…>" rather than an
 * arity error.
 */
type OptionsArgs<P extends PathsWith<M>, M extends HttpMethod> = P extends unknown
  ? object extends RequestOptions<P, M>
    ? [options?: RequestOptions<P, M>]
    : [options: RequestOptions<P, M>]
  : never;

/**
 * Body verbs. The body slot always exists (so the runtime never has to guess whether argument 2
 * is a body or the options), but it is typed `undefined` — and optional when nothing else is
 * required — for operations that declare no request body: `post(SIGNOUT)` compiles,
 * `post(SIGNOUT, { skipAuth: true })` does not (write `post(SIGNOUT, undefined, { skipAuth: true })`).
 */
type BodyArgs<P extends PathsWith<M>, M extends HttpMethod> = P extends unknown
  ? [RequestBody<P, M>] extends [never]
    ? object extends RequestOptions<P, M>
      ? [body?: undefined, options?: RequestOptions<P, M>]
      : [body: undefined, options: RequestOptions<P, M>]
    : [body: RequestBody<P, M>, ...OptionsArgs<P, M>]
  : never;

/** The type-erased view `request()` works with. */
interface RuntimeOptions extends RuntimeRequestOptions {
  skipAuth?: boolean;
}

// ── Error envelope ───────────────────────────────────────────────────────────────────────────

// `isErrorEnvelope`, `ApiError` and `SESSION_ENDED_MESSAGE` moved to ./api-error so the SSE client
// raises the very same error; `toApiError` below only adds the axios-specific cases.

// Extend axios config to include our custom metadata
declare module "axios" {
  interface AxiosRequestConfig {
    metadata?: {
      skipAuth?: boolean;
    };
  }
}

// Flag to prevent multiple simultaneous refresh attempts
let isRefreshing = false;
// Requests that 401'd while a refresh was already in flight park here. They are
// resumed with the new token, or rejected (null) when the refresh fails — so a
// failed refresh never strands them behind an unresolved promise.
let refreshSubscribers: Array<(token: string | null) => void> = [];

function subscribeTokenRefresh(cb: (token: string | null) => void) {
  refreshSubscribers.push(cb);
}

function onTokenRefreshed(token: string) {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
}

function onTokenRefreshFailed() {
  refreshSubscribers.forEach((cb) => cb(null));
  refreshSubscribers = [];
}

/**
 * Translate a non-401 axios failure into an `ApiError` (or a plain `Error` for network
 * failures). The envelope → message mapping is `apiErrorFromResponse` (./api-error).
 */
function toApiError(error: AxiosError): Error {
  if (error.response) {
    const { status, data } = error.response;
    return apiErrorFromResponse(status, data);
  }

  if (error.code === "ECONNABORTED") {
    return new Error("Request timeout. Please try again.");
  }
  return new Error("Network error. Please check your connection.");
}

/**
 * Create axios instance with interceptors for automatic token management
 */
function createAxiosInstance(baseUrl: string, timeout: number): AxiosInstance {
  const instance = axios.create({
    baseURL: baseUrl,
    timeout,
    headers: {
      "Content-Type": "application/json",
    },
  });

  // Request interceptor - add Authorization header unless skipAuth is set
  instance.interceptors.request.use(
    (config: InternalAxiosRequestConfig) => {
      const skipAuth = config.metadata?.skipAuth ?? false;

      if (!skipAuth) {
        const accessToken = tokenStorage.getAccessToken();
        if (accessToken) {
          config.headers.Authorization = `Bearer ${accessToken}`;
        }
      }
      return config;
    },
    (error) => Promise.reject(error)
  );

  // Response interceptor - handle 401 and auto-refresh (unless skipAuth)
  instance.interceptors.response.use(
    (response) => response,
    async (error: AxiosError) => {
      const originalRequest = error.config as InternalAxiosRequestConfig & {
        _retry?: boolean;
      };

      const skipAuth = originalRequest?.metadata?.skipAuth ?? false;

      // Handle 401 Unauthorized - attempt token refresh (unless skipAuth)
      if (error.response?.status === 401 && !skipAuth && !originalRequest._retry) {
        if (isRefreshing) {
          // A refresh is already in flight — wait for it, then resume or fail.
          return new Promise((resolve, reject) => {
            subscribeTokenRefresh((token) => {
              if (token) {
                originalRequest.headers.Authorization = `Bearer ${token}`;
                resolve(instance(originalRequest));
              } else {
                reject(new ApiError(401, SESSION_ENDED_MESSAGE));
              }
            });
          });
        }

        // Nothing to refresh with: the session is over, no round-trip needed.
        if (!tokenStorage.getRefreshToken()) {
          tokenStorage.clearTokens();
          throw new ApiError(401, SESSION_ENDED_MESSAGE);
        }

        originalRequest._retry = true;
        isRefreshing = true;

        let refreshError: unknown = null;
        let newToken: string | null = null;
        try {
          await refreshAuthToken();
          newToken = tokenStorage.getAccessToken();
        } catch (err) {
          refreshError = err;
        } finally {
          // Always release the lock. Leaving it `true` would strand every subsequent
          // request behind an unresolved queue — a hard deadlock.
          isRefreshing = false;
        }

        // Refresh succeeded and produced a usable access token — resume.
        if (!refreshError && newToken) {
          onTokenRefreshed(newToken);
          originalRequest.headers.Authorization = `Bearer ${newToken}`;
          return instance(originalRequest);
        }

        // Refresh failed, or resolved without a token. Wake queued waiters.
        onTokenRefreshFailed();

        // Preserve the session on a transient failure (network / CORS / timeout / 5xx)
        // so React Query can retry; only a definitive rejection (401/403) — or a refresh
        // that yielded no token — ends the session.
        if (refreshError && !isDefinitiveAuthFailure(refreshError)) {
          throw refreshError;
        }
        tokenStorage.clearTokens();
        throw new ApiError(401, SESSION_ENDED_MESSAGE);
      }

      throw toApiError(error);
    }
  );

  return instance;
}

/**
 * The one HTTP client. Every method is generic in the spec path only; the verb + path pick the
 * request body, the `path`/`query` options and the resolved type from the generated OpenAPI
 * types (`@/shared/api/types`). Templated paths take their segments through `options.path`:
 *
 *   apiClient.get("/api/organizations/{organization_id}", { path: { organization_id: id } })
 */
class ApiClient {
  private axiosInstance: AxiosInstance;

  constructor(baseUrl?: string, timeout = 30_000) {
    this.axiosInstance = createAxiosInstance(baseUrl ?? API_ENDPOINTS.EXTERNAL.BACKEND, timeout);
  }

  async get<P extends BodylessPaths<"get">>(
    path: P,
    ...[options]: OptionsArgs<P, "get">
  ): Promise<SuccessBody<P, "get">> {
    return this.request("get", path, undefined, options);
  }

  async post<P extends PathsWith<"post">>(
    path: P,
    ...[body, options]: BodyArgs<P, "post">
  ): Promise<SuccessBody<P, "post">> {
    return this.request("post", path, body, options);
  }

  async patch<P extends PathsWith<"patch">>(
    path: P,
    ...[body, options]: BodyArgs<P, "patch">
  ): Promise<SuccessBody<P, "patch">> {
    return this.request("patch", path, body, options);
  }

  async delete<P extends BodylessPaths<"delete">>(
    path: P,
    ...[options]: OptionsArgs<P, "delete">
  ): Promise<SuccessBody<P, "delete">> {
    return this.request("delete", path, undefined, options);
  }

  private async request<P extends PathsWith<M>, M extends HttpMethod>(
    method: M,
    path: P,
    body: unknown,
    options: RuntimeOptions | undefined
  ): Promise<SuccessBody<P, M>> {
    const response = await this.axiosInstance.request<SuccessBody<P, M>>({
      method,
      url: substitutePathParams(path, options?.path),
      data: body,
      params: options?.query,
      metadata: { skipAuth: options?.skipAuth },
    });
    return response.data;
  }
}

// Export primary singleton instance
export const apiClient = new ApiClient();
