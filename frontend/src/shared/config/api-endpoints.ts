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

  // Teams (a team belongs to an organization; conversations belong to a team)
  TEAMS: {
    MINE: "/api/teams",
    CREATE: "/api/organizations/{organization_id}/teams",
    TEAM: "/api/teams/{team_id}",
    MEMBERS: "/api/teams/{team_id}/members",
    MEMBER: "/api/teams/{team_id}/members/{user_id}",
  } satisfies Record<string, ApiPath>,

  // Chat: the model catalog, a team's conversations, a conversation's messages and runs.
  // RUN_EVENTS is `text/event-stream` — opened by `sse-client.ts`, not `apiClient`.
  CHAT: {
    MODELS: "/api/chat/models",
    CONVERSATIONS: "/api/teams/{team_id}/conversations",
    CONVERSATION: "/api/conversations/{conversation_id}",
    MESSAGES: "/api/conversations/{conversation_id}/messages",
    ACTIVE_RUN: "/api/conversations/{conversation_id}/runs/active",
    RUN: "/api/conversations/{conversation_id}/runs/{run_id}",
    CANCEL_RUN: "/api/conversations/{conversation_id}/runs/{run_id}/cancel",
    RUN_EVENTS: "/api/conversations/{conversation_id}/runs/{run_id}/events",
  } satisfies Record<string, ApiPath>,

  // Attachments: uploaded per team before the message that claims them. UPLOAD is multipart
  // (`apiClient.upload`); CONTENT serves the bytes (`apiClient.blob` — bearer-protected, so it
  // is never used as a raw `src`).
  ATTACHMENTS: {
    UPLOAD: "/api/teams/{team_id}/attachments",
    ATTACHMENT: "/api/attachments/{attachment_id}",
    CONTENT: "/api/attachments/{attachment_id}/content",
  } satisfies Record<string, ApiPath>,
} as const;
