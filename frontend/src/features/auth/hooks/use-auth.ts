import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { QUERY_KEYS } from "@/shared/constants/query-keys";
import { ROUTES } from "@/shared/constants/routes";

import { authService } from "../services/auth.service";
import type {
  ForgotPasswordRequest,
  ResetPasswordRequest,
  SessionUser,
  SignInCredentials,
  SignUpCredentials,
} from "../types";

/**
 * The session query. Runs once on app start (via `AuthProvider`) and restores a persisted
 * session from the refresh token — see `AuthService.getCurrentUser`.
 */
export function useCurrentUser() {
  // Typed `SessionUser`, not `UserProfile`, even though the queryFn returns the latter:
  // `useSignUp` seeds this same key with the narrower sign-up shape, so the cache genuinely
  // holds either one.
  return useQuery<SessionUser | null>({
    queryKey: QUERY_KEYS.auth.user,
    queryFn: () => authService.getCurrentUser(),
    staleTime: 1000 * 60 * 5,
    // No retry override on purpose: inherit the app-wide policy (query-provider.tsx) that
    // retries 5xx/network up to 3x but never 4xx. getCurrentUser resolves null for a genuine
    // logout and only rethrows transient failures, so a blip is retried instead of
    // bouncing the user to the login screen.
    throwOnError: false,
  });
}

export function useSignIn() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  return useMutation({
    mutationFn: (credentials: SignInCredentials) => authService.signIn(credentials),
    onSuccess: async () => {
      // Sign-in returns only tokens. Load the profile before entering the app so the
      // protected layout never sees a `null` user and bounces back to login.
      await queryClient.invalidateQueries({ queryKey: QUERY_KEYS.auth.user });
      navigate(ROUTES.app.root, { replace: true });
    },
  });
}

export function useSignUp() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  return useMutation({
    mutationFn: (credentials: SignUpCredentials) => authService.signUp(credentials),
    onSuccess: (data) => {
      // Tokens were stored by AuthService; the response carries the user, so seed the
      // session cache directly instead of a second round-trip.
      queryClient.setQueryData<SessionUser | null>(QUERY_KEYS.auth.user, data.user);
      navigate(ROUTES.app.root, { replace: true });
    },
  });
}

/** Request a reset link. Nothing to cache or navigate to: the form shows the confirmation itself. */
export function useForgotPassword() {
  return useMutation({
    mutationFn: (body: ForgotPasswordRequest) => authService.forgotPassword(body),
  });
}

/** Redeem a reset link. No session is created: the form offers the sign-in page afterwards. */
export function useResetPassword() {
  return useMutation({
    mutationFn: (body: ResetPasswordRequest) => authService.resetPassword(body),
  });
}

export function useSignOut() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  return useMutation({
    mutationFn: () => authService.signOut(),
    // `onSettled`, not `onSuccess`: the local tokens are gone either way (see
    // AuthService.signOut), so the UI must leave the app even if the revoke call failed.
    onSettled: () => {
      queryClient.setQueryData<SessionUser | null>(QUERY_KEYS.auth.user, null);
      // Feature caches must not leak into the next user's session: remove every query
      // except the session itself (already reset above) as features are added.
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== QUERY_KEYS.auth.user[0],
      });
      navigate(ROUTES.auth.login, { replace: true });
    },
  });
}
