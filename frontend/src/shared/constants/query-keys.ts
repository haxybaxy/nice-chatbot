/**
 * Centralized query keys for all features, organized hierarchically so prefixes can be
 * invalidated as a group (`QUERY_KEYS.<feature>.all`).
 */
export const QUERY_KEYS = {
  auth: {
    /** The session cache — see `SessionUser` in features/auth/types. */
    user: ["auth", "user"] as const,
  },
  teams: {
    all: ["teams"] as const,
    /** `GET /api/teams` — the caller's teams. */
    mine: ["teams", "mine"] as const,
    members: (teamId: string) => ["teams", teamId, "members"] as const,
  },
  chat: {
    all: ["chat"] as const,
    /** `GET /api/chat/models` — never stale. */
    models: ["chat", "models"] as const,
    /** A team's conversation list (infinite query on `nextCursor`). */
    conversations: (teamId: string) => ["chat", "conversations", teamId] as const,
    /** One conversation with its persisted messages. */
    conversation: (conversationId: string) => ["chat", "conversation", conversationId] as const,
  },
} as const;
