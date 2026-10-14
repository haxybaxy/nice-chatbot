import type { AuthTokens, AuthUser, UserProfile } from "@/features/auth/types";
import { createFakeJWT } from "@/test/test-utils";

let counter = 1;

/**
 * The sign-up shape (`AuthUserOut`). Deliberately does NOT carry `updatedAt` — the backend
 * doesn't send it here, and a mock that did would certify a response shape that cannot
 * exist. Use {@link makeUserProfile} for `/users/me`.
 */
export function makeAuthUser(overrides: Partial<AuthUser> = {}): AuthUser {
  const id = overrides.id ?? `user-${counter++}`;
  return {
    id,
    email: `${id}@example.com`,
    fullName: "Test User",
    createdAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/** The `GET` / `PATCH /api/users/me` shape (`UserOut`). */
export function makeUserProfile(overrides: Partial<UserProfile> = {}): UserProfile {
  return {
    ...makeAuthUser(overrides),
    updatedAt: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

/** An unexpired access token, shaped like the Cognito JWT the app decodes for expiry. */
export function makeAccessToken(sub = "user-1"): string {
  return createFakeJWT({ sub, exp: Math.floor(Date.now() / 1000) + 3600 });
}

/** A token pair as every auth endpoint returns it (`TokensOut`). */
export function makeTokens(overrides: Partial<AuthTokens> = {}): AuthTokens {
  return {
    accessToken: makeAccessToken(),
    refreshToken: "refresh-token-1",
    expiresIn: 3600,
    tokenType: "bearer",
    ...overrides,
  };
}
