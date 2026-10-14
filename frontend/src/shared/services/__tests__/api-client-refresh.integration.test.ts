import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// Importing the auth service registers the refresh handler with auth-bridge, exactly as the
// app does at startup.
import "@/features/auth/services/auth.service";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { ApiError, apiClient } from "@/shared/services/api-client";
import { tokenStorage } from "@/shared/services/token-storage";
import { errorResponse } from "@/test/msw/fixtures/error";
import { makeTokens, makeUserProfile } from "@/test/msw/fixtures/user";
import { server } from "@/test/msw/server";
import { mockApi } from "@/test/msw/typed-http";

describe("apiClient 401 handling", () => {
  it("refreshes once and retries the original request with the new token", async () => {
    const seen: string[] = [];
    server.use(
      mockApi.get(API_ENDPOINTS.USERS.ME, ({ request }) => {
        const auth = request.headers.get("authorization");
        seen.push(auth ?? "none");
        if (auth === "Bearer fresh") {
          return HttpResponse.json(makeUserProfile({ email: "me@example.com" }));
        }
        return errorResponse(401, "AUTH_FAILED", "Token expired");
      }),
      mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () =>
        HttpResponse.json(makeTokens({ accessToken: "fresh", refreshToken: "rt-2" }))
      )
    );
    tokenStorage.setTokens({ accessToken: "stale", refreshToken: "rt-1", expiresIn: 3600 });

    const user = await apiClient.get(API_ENDPOINTS.USERS.ME);

    expect(user.email).toBe("me@example.com");
    expect(seen).toEqual(["Bearer stale", "Bearer fresh"]);
    expect(tokenStorage.getRefreshToken()).toBe("rt-2");
  });

  it("shares one refresh between concurrent 401s", async () => {
    let refreshes = 0;
    server.use(
      mockApi.get(API_ENDPOINTS.USERS.ME, ({ request }) =>
        request.headers.get("authorization") === "Bearer fresh"
          ? HttpResponse.json(makeUserProfile({ email: "me@example.com" }))
          : errorResponse(401, "AUTH_FAILED", "Token expired")
      ),
      mockApi.post(API_ENDPOINTS.AUTH.REFRESH, async () => {
        refreshes += 1;
        await new Promise((resolve) => setTimeout(resolve, 20));
        return HttpResponse.json(makeTokens({ accessToken: "fresh", refreshToken: "rt-2" }));
      })
    );
    tokenStorage.setTokens({ accessToken: "stale", refreshToken: "rt-1", expiresIn: 3600 });

    const results = await Promise.all([
      apiClient.get(API_ENDPOINTS.USERS.ME),
      apiClient.get(API_ENDPOINTS.USERS.ME),
      apiClient.get(API_ENDPOINTS.USERS.ME),
    ]);

    expect(results.map((r) => r.email)).toEqual(Array(3).fill("me@example.com"));
    expect(refreshes).toBe(1);
  });

  it("ends the session when the refresh token is rejected", async () => {
    server.use(
      mockApi.get(API_ENDPOINTS.USERS.ME, () => errorResponse(401, "AUTH_FAILED", "Token expired")),
      mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () =>
        errorResponse(401, "AUTH_FAILED", "Invalid or expired refresh token")
      )
    );
    tokenStorage.setTokens({ accessToken: "stale", refreshToken: "rt-1", expiresIn: 3600 });

    const failure = await apiClient.get(API_ENDPOINTS.USERS.ME).catch((e: unknown) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(401);
    expect(tokenStorage.getRefreshToken()).toBeNull();
  });

  it("does not refresh for requests marked skipAuth and surfaces the backend envelope", async () => {
    let refreshes = 0;
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.SIGNIN, () =>
        errorResponse(401, "AUTH_FAILED", "Incorrect email or password")
      ),
      mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () => {
        refreshes += 1;
        return HttpResponse.json(makeTokens({ accessToken: "x", refreshToken: "y", expiresIn: 1 }));
      })
    );

    const failure = await apiClient
      .post(
        API_ENDPOINTS.AUTH.SIGNIN,
        { email: "a@example.com", password: "nope" },
        { skipAuth: true }
      )
      .catch((e: unknown) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).message).toBe("Incorrect email or password");
    expect((failure as ApiError).code).toBe("AUTH_FAILED");
    expect((failure as ApiError).correlationId).toBe("c-1");
    expect(refreshes).toBe(0);
  });
});
