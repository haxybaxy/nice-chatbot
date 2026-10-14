/**
 * Centralized query keys for all features, organized hierarchically so prefixes can be
 * invalidated as a group (`QUERY_KEYS.<feature>.all`).
 */
export const QUERY_KEYS = {
  auth: {
    /** The session cache — see `SessionUser` in features/auth/types. */
    user: ["auth", "user"] as const,
  },
} as const;
