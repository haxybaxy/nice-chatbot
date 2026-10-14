/**
 * Centralized localStorage keys for all features.
 * Prevents typos and makes it easy to track what's stored.
 */
export const STORAGE_KEYS = {
  // Theme
  THEME: "theme",

  // Auth (managed by shared/services/token-storage.ts)
  REFRESH_TOKEN: "refresh_token",

  // Teams: the team `/app` redirects to (cleared on sign-out)
  LAST_TEAM_ID: "last_team_id",

  // Chat: the composer's remembered settings (model, mode, tool toggles)
  CHAT_COMPOSER: "chat_composer",
} as const;
