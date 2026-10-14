import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { STORAGE_KEYS } from "@/shared/constants/storage-keys";
import { makeTokens, makeUserProfile } from "@/test/msw/fixtures/user";
import { server } from "@/test/msw/server";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

/**
 * The persistence guarantee, at the boundary: a fresh app load (no in-memory access token)
 * with a refresh token in localStorage must land on the protected page, not on login.
 */
describe("session persistence across reloads", () => {
  it("restores the session from the refresh token alone and shows the home page", async () => {
    const calls: string[] = [];
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () => {
        calls.push("refresh");
        return HttpResponse.json(makeTokens());
      }),
      mockApi.get(API_ENDPOINTS.USERS.ME, () => {
        calls.push("me");
        return HttpResponse.json(
          makeUserProfile({ email: "persisted@example.com", fullName: "Persisted User" })
        );
      })
    );
    // Only the refresh token survives a reload.
    localStorage.setItem(STORAGE_KEYS.REFRESH_TOKEN, "refresh-token-1");

    renderWithProviders(<App />, { authenticated: false, route: "/app" });

    expect(await screen.findByText("Welcome, Persisted User")).toBeInTheDocument();
    expect(screen.getByText("persisted@example.com", { selector: "dd" })).toBeInTheDocument();
    expect(calls).toEqual(["refresh", "me"]);
  });

  it("sends a visitor without a session to the login page", async () => {
    renderWithProviders(<App />, { authenticated: false, route: "/app" });

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("sends a signed-in visitor away from the login page", async () => {
    localStorage.setItem(STORAGE_KEYS.REFRESH_TOKEN, "refresh-token-1");
    server.use(mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () => HttpResponse.json(makeTokens())));

    renderWithProviders(<App />, { authenticated: false, route: "/auth/login" });

    expect(await screen.findByText(/^Welcome/)).toBeInTheDocument();
  });

  it("signs out: revokes on the backend, forgets the tokens and returns to login", async () => {
    const user = userEvent.setup();
    let revoked = false;
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.SIGNOUT, () => {
        revoked = true;
        return new HttpResponse(null, { status: 204 });
      })
    );

    renderWithProviders(<App />, { route: "/app" });
    await user.click(await screen.findByRole("button", { name: /sign out/i }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await waitFor(() => expect(revoked).toBe(true));
    expect(localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN)).toBeNull();
  });
});
