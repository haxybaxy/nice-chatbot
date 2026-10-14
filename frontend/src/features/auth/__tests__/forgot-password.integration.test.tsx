import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import type { ForgotPasswordRequest } from "@/features/auth";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { errorResponse } from "@/test/msw/fixtures/error";
import { server } from "@/test/msw/server";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

describe("forgot password", () => {
  it("is reachable from the login page", async () => {
    const user = userEvent.setup();
    renderWithProviders(<App />, { authenticated: false, route: "/auth/login" });

    await user.click(await screen.findByRole("link", { name: "Forgot your password?" }));

    expect(await screen.findByRole("heading", { name: "Reset your password" })).toBeInTheDocument();
  });

  it("validates the email before sending", async () => {
    const user = userEvent.setup();
    let requests = 0;
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.FORGOT_PASSWORD, () => {
        requests += 1;
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<App />, { authenticated: false, route: "/auth/forgot-password" });

    await user.type(await screen.findByLabelText("Email"), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
    expect(requests).toBe(0);
  });

  it("sends the address and confirms without revealing whether an account exists", async () => {
    const user = userEvent.setup();
    let body: ForgotPasswordRequest | null = null;
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.FORGOT_PASSWORD, async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<App />, { authenticated: false, route: "/auth/forgot-password" });

    await user.type(await screen.findByLabelText("Email"), "me@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByRole("heading", { name: "Check your inbox" })).toBeInTheDocument();
    expect(screen.getByText(/me@example\.com/)).toBeInTheDocument();
    expect(body).toEqual({ email: "me@example.com" });
  });

  it("shows a server failure and keeps the form", async () => {
    const user = userEvent.setup();
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.FORGOT_PASSWORD, () =>
        errorResponse(503, "SERVICE_UNAVAILABLE", "Email service is busy, please retry")
      )
    );
    renderWithProviders(<App />, { authenticated: false, route: "/auth/forgot-password" });

    await user.type(await screen.findByLabelText("Email"), "me@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByText("Server error. Please try again later.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });
});
