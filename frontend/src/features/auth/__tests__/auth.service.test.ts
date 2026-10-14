import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { tokenStorage } from "@/shared/services/token-storage";
import { errorResponse } from "@/test/msw/fixtures/error";
import { makeAccessToken, makeTokens, makeUserProfile } from "@/test/msw/fixtures/user";
import { server } from "@/test/msw/server";
import { mockApi } from "@/test/msw/typed-http";

import { authService } from "../services/auth.service";

describe("authService", () => {
  describe("signIn / signUp", () => {
    it("stores the token pair returned by sign-in", async () => {
      await authService.signIn({ email: "a@example.com", password: "password123" });

      expect(tokenStorage.isAccessTokenExpired()).toBe(false);
      expect(tokenStorage.getRefreshToken()).toBe("refresh-token-1");
    });

    it("stores the tokens that come with the sign-up response and returns the user", async () => {
      const response = await authService.signUp({
        email: "new@example.com",
        password: "password123",
        fullName: null,
      });

      expect(response.user.email).toBe("new@example.com");
      expect(tokenStorage.getRefreshToken()).toBe("refresh-token-1");
    });
  });

  describe("getCurrentUser (session restore)", () => {
    it("resolves null without any tokens and makes no request", async () => {
      let requests = 0;
      server.use(
        mockApi.get(API_ENDPOINTS.USERS.ME, () => {
          requests += 1;
          return errorResponse(500, "INTERNAL_ERROR");
        })
      );

      await expect(authService.getCurrentUser()).resolves.toBeNull();
      expect(requests).toBe(0);
    });

    it("refreshes first when only the refresh token survived (a reload), then loads the profile", async () => {
      const calls: string[] = [];
      server.use(
        mockApi.post(API_ENDPOINTS.AUTH.REFRESH, async ({ request }) => {
          const body = await request.json(); // `RefreshIn`
          calls.push(`refresh:${body.refreshToken}`);
          return HttpResponse.json(
            makeTokens({ accessToken: makeAccessToken(), refreshToken: "refresh-token-rotated" })
          );
        }),
        mockApi.get(API_ENDPOINTS.USERS.ME, ({ request }) => {
          calls.push(`me:${request.headers.get("authorization")?.startsWith("Bearer ") ?? false}`);
          return HttpResponse.json(makeUserProfile({ email: "persisted@example.com" }));
        })
      );
      localStorage.setItem("refresh_token", "refresh-token-persisted");

      const user = await authService.getCurrentUser();

      expect(user?.email).toBe("persisted@example.com");
      expect(calls).toEqual(["refresh:refresh-token-persisted", "me:true"]);
      expect(tokenStorage.getRefreshToken()).toBe("refresh-token-rotated");
    });

    it("resolves null and forgets the refresh token when the backend rejects it", async () => {
      server.use(
        mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () =>
          errorResponse(401, "AUTH_FAILED", "Invalid or expired refresh token")
        )
      );
      localStorage.setItem("refresh_token", "stale");

      await expect(authService.getCurrentUser()).resolves.toBeNull();
      expect(tokenStorage.getRefreshToken()).toBeNull();
    });

    it("keeps the refresh token and rethrows on a transient refresh failure", async () => {
      server.use(mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () => HttpResponse.error()));
      localStorage.setItem("refresh_token", "still-good");

      await expect(authService.getCurrentUser()).rejects.toBeDefined();
      expect(tokenStorage.getRefreshToken()).toBe("still-good");
    });

    it("skips the refresh when the in-memory access token is still valid", async () => {
      let refreshes = 0;
      server.use(
        mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () => {
          refreshes += 1;
          return errorResponse(500, "INTERNAL_ERROR");
        })
      );
      tokenStorage.setTokens(makeTokens({ refreshToken: "rt" }));

      const user = await authService.getCurrentUser();

      expect(user?.id).toBe("user-1");
      expect(refreshes).toBe(0);
    });
  });

  describe("signOut", () => {
    it("sends the bearer token and clears the local pair", async () => {
      let authHeader: string | null = null;
      server.use(
        mockApi.post(API_ENDPOINTS.AUTH.SIGNOUT, ({ request }) => {
          authHeader = request.headers.get("authorization");
          return new HttpResponse(null, { status: 204 });
        })
      );
      tokenStorage.setTokens(makeTokens({ refreshToken: "rt" }));

      await authService.signOut();

      expect(authHeader).toMatch(/^Bearer /);
      expect(tokenStorage.getAccessToken()).toBeNull();
      expect(tokenStorage.getRefreshToken()).toBeNull();
    });

    it("clears the local pair even when the revoke call fails", async () => {
      server.use(mockApi.post(API_ENDPOINTS.AUTH.SIGNOUT, () => HttpResponse.error()));
      tokenStorage.setTokens(makeTokens({ refreshToken: "rt" }));

      await expect(authService.signOut()).rejects.toBeDefined();
      expect(tokenStorage.getRefreshToken()).toBeNull();
    });
  });
});
