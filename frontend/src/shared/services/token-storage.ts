/**
 * Token storage.
 *
 * The access token lives in memory only (gone on a hard reload, never readable by other
 * tabs or scripts); the refresh token lives in localStorage so the session survives
 * reloads — `AuthService.getCurrentUser` mints a fresh access token from it on startup.
 *
 * Lives in `shared/services` (not `features/auth`) because `api-client.ts` reads it on every
 * request; `shared` never imports a feature (fallow boundaries).
 */

import type { Schema } from "@/shared/api/types";
import { STORAGE_KEYS } from "@/shared/constants/storage-keys";
import { storage } from "@/shared/services/local-storage";

/** Bearer tokens as every auth endpoint returns them (`features/auth` aliases this as `AuthTokens`). */
type TokenPair = Schema<"TokensOut">;

class TokenStorageService {
  private accessToken: string | null = null;

  /** Store a token pair from sign-up / sign-in / refresh. */
  setTokens(tokens: TokenPair): void {
    this.accessToken = tokens.accessToken;
    storage.setString(STORAGE_KEYS.REFRESH_TOKEN, tokens.refreshToken);
  }

  /** The in-memory access token, or `null` after a reload / sign-out. */
  getAccessToken(): string | null {
    return this.accessToken;
  }

  /** The persisted refresh token, or `null` when signed out. */
  getRefreshToken(): string | null {
    return storage.getString(STORAGE_KEYS.REFRESH_TOKEN);
  }

  /** Forget both tokens (sign-out, or a definitive refresh failure). */
  clearTokens(): void {
    this.accessToken = null;
    storage.remove(STORAGE_KEYS.REFRESH_TOKEN);
  }

  /** Decode a JWT payload without verifying it (expiry checks only — never trust claims). */
  decodeJWT(token: string): Record<string, unknown> | null {
    try {
      const base64Url = token.split(".")[1];
      if (!base64Url) return null;
      const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
      const jsonPayload = decodeURIComponent(
        atob(base64)
          .split("")
          .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
          .join("")
      );
      return JSON.parse(jsonPayload) as Record<string, unknown>;
    } catch {
      return null;
    }
  }

  /**
   * Whether the access token is missing, undecodable, or within 10 seconds of expiry.
   *
   * The buffer is small on purpose: long enough for a refresh round-trip to land before the
   * token actually expires, short enough that several components noticing "expired" at
   * once don't fan out into a burst of refreshes.
   */
  isAccessTokenExpired(): boolean {
    if (!this.accessToken) return true;

    const payload = this.decodeJWT(this.accessToken);
    if (!payload || !payload["exp"]) return true;

    const exp = typeof payload["exp"] === "number" ? payload["exp"] : Number(payload["exp"]);
    return Date.now() >= (exp - 10) * 1000;
  }
}

export const tokenStorage = new TokenStorageService();
