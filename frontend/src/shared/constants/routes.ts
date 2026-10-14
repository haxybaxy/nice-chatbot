/**
 * Centralized route paths for all features.
 * Prevents typos and makes refactoring safe.
 */
export const ROUTES = {
  // Auth (guest only)
  auth: {
    root: "/auth",
    login: "/auth/login",
    signUp: "/auth/sign-up",
    forgotPassword: "/auth/forgot-password",
    // The backend mails exactly this path with `?token=…` (FRONTEND_URL + /auth/reset-password).
    resetPassword: "/auth/reset-password",
  },

  // App (protected)
  app: {
    root: "/app",
  },
} as const;
