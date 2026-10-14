/**
 * Centralized localStorage keys for all features.
 * Prevents typos and makes it easy to track what's stored.
 */
export const STORAGE_KEYS = {
  // Theme
  THEME: "theme",

  // Auth (managed by shared/services/token-storage.ts)
  REFRESH_TOKEN: "refresh_token",
} as const;
