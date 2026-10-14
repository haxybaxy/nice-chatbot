/**
 * Auth types.
 *
 * Response and request shapes are aliases of the generated wire types (`Schema<"…">`), so a
 * backend rename is a compile error here rather than a runtime surprise. The one hand-written
 * type is {@link SessionUser}, which names a client-side CACHE state with no wire counterpart.
 */
import type { Schema } from "@/shared/api/types";

/** `POST /api/auth/signin` body. */
export type SignInCredentials = Schema<"SignInIn">;

/** `POST /api/auth/signup` body. `fullName` is optional and nullable on the wire. */
export type SignUpCredentials = Schema<"SignUpIn">;

/** `POST /api/auth/refresh` body. */
export type RefreshRequest = Schema<"RefreshIn">;

/** `POST /api/auth/forgot-password` body. */
export type ForgotPasswordRequest = Schema<"ForgotPasswordIn">;

/** `POST /api/auth/reset-password` body: the mailed token and the new password. */
export type ResetPasswordRequest = Schema<"ResetPasswordIn">;

/** Bearer tokens as every auth endpoint returns them (`TokensOut`). */
export type AuthTokens = Schema<"TokensOut">;

/**
 * The user as `POST /api/auth/signup` returns them (`AuthUserOut`). Deliberately narrower
 * than {@link UserProfile}: the backend does not declare `updatedAt` on this schema, so a
 * single conflated type would claim a field that never arrives.
 */
export type AuthUser = Schema<"AuthUserOut">;

/** The user as `GET` / `PATCH /api/users/me` return them (`UserOut`). */
export type UserProfile = Schema<"UserOut">;

/** The personal organization `POST /api/auth/signup` creates for the new user (`AuthOrganizationOut`). */
export type AuthOrganization = Schema<"AuthOrganizationOut">;

/** The default team sign-up creates in that organization (`AuthTeamOut`). */
export type AuthTeam = Schema<"AuthTeamOut">;

/** `POST /api/auth/signup` result: the new user, their organization and team, plus a signed-in session. */
export type SignUpResponse = Schema<"SignUpOut">;

/**
 * What the `QUERY_KEYS.auth.user` cache actually holds.
 *
 * It is seeded with an {@link AuthUser} by sign-up and replaced by a {@link UserProfile}
 * once `/users/me` answers, so the profile-only fields are optional **here and only here** —
 * that is a real runtime state, not looseness. Read them with a default, never assume
 * they are present.
 */
export type SessionUser = AuthUser & Partial<UserProfile>;
