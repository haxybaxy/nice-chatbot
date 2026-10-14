import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import type { SignInCredentials } from "@/features/auth";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { STORAGE_KEYS } from "@/shared/constants/storage-keys";
import { errorResponse } from "@/test/msw/fixtures/error";
import { makeTokens } from "@/test/msw/fixtures/user";
import { server } from "@/test/msw/server";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

describe("LoginForm", () => {
  it("validates before submitting", async () => {
    const user = userEvent.setup();
    let requests = 0;
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.SIGNIN, () => {
        requests += 1;
        return errorResponse(500, "INTERNAL_ERROR");
      })
    );
    renderWithProviders(<App />, { authenticated: false, route: "/auth/login" });

    await user.type(await screen.findByLabelText("Email"), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
    expect(screen.getByText("Password is required")).toBeInTheDocument();
    expect(requests).toBe(0);
  });

  it("signs in, persists the refresh token and enters the app", async () => {
    const user = userEvent.setup();
    let body: SignInCredentials | null = null;
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.SIGNIN, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(makeTokens({ refreshToken: "refresh-token-1" }));
      })
    );
    renderWithProviders(<App />, { authenticated: false, route: "/auth/login" });

    await user.type(await screen.findByLabelText("Email"), "me@example.com");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText(/^Welcome/)).toBeInTheDocument();
    expect(body).toEqual({ email: "me@example.com", password: "password123" });
    expect(localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN)).toBe("refresh-token-1");
  });

  it("shows the backend's error message on a rejected sign-in", async () => {
    const user = userEvent.setup();
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.SIGNIN, () =>
        errorResponse(401, "AUTH_FAILED", "Incorrect email or password")
      )
    );
    renderWithProviders(<App />, { authenticated: false, route: "/auth/login" });

    await user.type(await screen.findByLabelText("Email"), "me@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Incorrect email or password")).toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN)).toBeNull();
  });
});
