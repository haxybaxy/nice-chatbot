/**
 * Centralized API endpoint configuration.
 *
 * Every path the app calls lives here; services import these constants instead of hardcoding
 * strings, and the MSW handlers register against the same constants. Each group `satisfies
 * Record<string, ApiPath>`, so a path the backend does not declare (a typo, a renamed route)
 * is a compile error, and `apiClient` derives request/response types from the literal.
 */
import type { ApiPath } from "@/shared/api/types";

const getBackendUrl = (): string => {
  // Use the configured origin or fall back to the local backend (`just dev` in ../backend).
  return import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
};

export const API_ENDPOINTS = {
  /** Base URL, not a spec path — deliberately outside the `satisfies` guard. */
  EXTERNAL: {
    BACKEND: getBackendUrl(),
  },

  // Authentication (backend-proxied Cognito; see backend/README.md)
  AUTH: {
    SIGNUP: "/api/auth/signup",
    SIGNIN: "/api/auth/signin",
    SIGNOUT: "/api/auth/signout",
    REFRESH: "/api/auth/refresh",
    FORGOT_PASSWORD: "/api/auth/forgot-password",
    RESET_PASSWORD: "/api/auth/reset-password",
  } satisfies Record<string, ApiPath>,

  // Users
  USERS: {
    ME: "/api/users/me",
  } satisfies Record<string, ApiPath>,
} as const;
