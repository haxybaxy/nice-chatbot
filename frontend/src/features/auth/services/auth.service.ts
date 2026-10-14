import axios from "axios";

import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { apiClient } from "@/shared/services/api-client";
import { setAuthRefreshHandler } from "@/shared/services/auth-bridge";
import { isDefinitiveAuthFailure } from "@/shared/services/refresh-error";
import { tokenStorage } from "@/shared/services/token-storage";

import type {
  AuthTokens,
  ForgotPasswordRequest,
  RefreshRequest,
  ResetPasswordRequest,
  SignInCredentials,
  SignUpCredentials,
  SignUpResponse,
  UserProfile,
} from "../types";

/**
 * Authentication service — the only module that talks to `/api/auth/*`.
 *
 * Tokens are stored by {@link tokenStorage} (access token in memory, refresh token in
 * localStorage). The api-client interceptor calls {@link AuthService.refreshToken} through
 * `auth-bridge` on a 401, and {@link AuthService.getCurrentUser} calls it on startup — that
 * second path is what keeps a user signed in across reloads.
 */
class AuthService {
  // Single-flight refresh: the interceptor, getCurrentUser and any future caller share one
  // in-flight request instead of racing Cognito with the same refresh token.
  private refreshPromise: Promise<AuthTokens> | null = null;

  /** Create the account. The backend signs the new user in, so tokens arrive with the user. */
  async signUp(credentials: SignUpCredentials): Promise<SignUpResponse> {
    const response = await apiClient.post(API_ENDPOINTS.AUTH.SIGNUP, credentials, {
      skipAuth: true,
    });
    tokenStorage.setTokens(response.tokens);
    return response;
  }

  /** Exchange email + password for a token pair. */
  async signIn(credentials: SignInCredentials): Promise<AuthTokens> {
    const tokens = await apiClient.post(API_ENDPOINTS.AUTH.SIGNIN, credentials, {
      skipAuth: true,
    });
    tokenStorage.setTokens(tokens);
    return tokens;
  }

  /** Ask for a reset link. Always resolves: the backend answers 204 whether or not the address has an account. */
  async forgotPassword(body: ForgotPasswordRequest): Promise<void> {
    await apiClient.post(API_ENDPOINTS.AUTH.FORGOT_PASSWORD, body, { skipAuth: true });
  }

  /** Redeem a mailed reset token for a new password; the backend revokes every session of the user. */
  async resetPassword(body: ResetPasswordRequest): Promise<void> {
    await apiClient.post(API_ENDPOINTS.AUTH.RESET_PASSWORD, body, { skipAuth: true });
  }

  /**
   * Revoke every refresh token of the caller (the endpoint needs the bearer token), then
   * forget the local pair. Tokens are cleared even if the revoke call fails — the user asked
   * to leave, and a stale refresh token is only good until its 30-day lifetime anyway.
   */
  async signOut(): Promise<void> {
    try {
      await apiClient.post(API_ENDPOINTS.AUTH.SIGNOUT);
    } finally {
      tokenStorage.clearTokens();
    }
  }

  /**
   * Mint a new access token from the stored refresh token. Concurrent callers get the same
   * promise. Rejects with the raw axios error so callers can classify it (see
   * `isDefinitiveAuthFailure`).
   */
  async refreshToken(): Promise<AuthTokens> {
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    const refreshToken = tokenStorage.getRefreshToken();
    if (!refreshToken) {
      throw new Error("No refresh token available");
    }

    this.refreshPromise = this.performRefresh(refreshToken);
    try {
      return await this.refreshPromise;
    } finally {
      this.refreshPromise = null;
    }
  }

  /**
   * The actual refresh call, on a bare axios instance: going through `apiClient` would put
   * this request behind the very interceptor that is waiting for it. This is the one sanctioned
   * raw-axios call (ESLint bans `axios` elsewhere); its body and result are still wire types.
   */
  private async performRefresh(refreshToken: string): Promise<AuthTokens> {
    const body: RefreshRequest = { refreshToken };
    try {
      const response = await axios.post<AuthTokens>(
        `${API_ENDPOINTS.EXTERNAL.BACKEND}${API_ENDPOINTS.AUTH.REFRESH}`,
        body,
        { headers: { "Content-Type": "application/json" } }
      );
      // The backend echoes the refresh token back when Cognito doesn't rotate it, so this
      // always stores a complete pair.
      tokenStorage.setTokens(response.data);
      return response.data;
    } catch (error) {
      // Only a rejection by the backend (401/403) ends the session. On a transient failure
      // (network, timeout, 5xx) the refresh token may still be valid — keep it so the caller
      // can retry instead of forcing a full re-login.
      if (isDefinitiveAuthFailure(error)) {
        tokenStorage.clearTokens();
      }
      throw error;
    }
  }

  /**
   * Restore the session and fetch the profile. Resolves `null` for "not signed in" (no
   * tokens, or the backend rejected them) and rethrows transient failures so React Query
   * retries instead of dropping the user at the login screen.
   *
   * On a hard reload the in-memory access token is gone but the refresh token persists;
   * refreshing first avoids a guaranteed 401 round-trip on `/users/me`.
   */
  async getCurrentUser(): Promise<UserProfile | null> {
    if (!tokenStorage.getAccessToken() && !tokenStorage.getRefreshToken()) {
      return null;
    }

    if (tokenStorage.isAccessTokenExpired() && tokenStorage.getRefreshToken()) {
      try {
        await this.refreshToken();
      } catch (error) {
        if (isDefinitiveAuthFailure(error)) {
          return null;
        }
        throw error;
      }
    }

    try {
      return await apiClient.get(API_ENDPOINTS.USERS.ME);
    } catch (error) {
      if (isDefinitiveAuthFailure(error)) {
        return null;
      }
      throw error;
    }
  }
}

export const authService = new AuthService();

setAuthRefreshHandler(async () => {
  await authService.refreshToken();
});
