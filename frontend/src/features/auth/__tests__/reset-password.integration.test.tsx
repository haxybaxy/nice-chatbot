import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import type { ResetPasswordRequest } from "@/features/auth";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { errorResponse } from "@/test/msw/fixtures/error";
import { server } from "@/test/msw/server";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

const ROUTE = "/auth/reset-password?token=abc";

describe("reset password", () => {
  it("validates before submitting", async () => {
    const user = userEvent.setup();
    let requests = 0;
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.RESET_PASSWORD, () => {
        requests += 1;
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<App />, { authenticated: false, route: ROUTE });

    await user.type(await screen.findByLabelText("New password"), "short");
    await user.type(screen.getByLabelText("Confirm new password"), "different");
    await user.click(screen.getByRole("button", { name: "Update password" }));

    expect(await screen.findByText("Password must be at least 8 characters")).toBeInTheDocument();
    expect(screen.getByText("Passwords do not match")).toBeInTheDocument();
    expect(requests).toBe(0);
  });

  it("updates the password with the wire fields only and offers to sign in", async () => {
    const user = userEvent.setup();
    let body: ResetPasswordRequest | null = null;
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.RESET_PASSWORD, async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<App />, { authenticated: false, route: ROUTE });

    await user.type(await screen.findByLabelText("New password"), "password123");
    await user.type(screen.getByLabelText("Confirm new password"), "password123");
    await user.click(screen.getByRole("button", { name: "Update password" }));

    expect(await screen.findByRole("heading", { name: "Password updated" })).toBeInTheDocument();
    expect(body).toEqual({ token: "abc", password: "password123" });

    await user.click(screen.getByRole("link", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the backend's rejection and offers a new link", async () => {
    const user = userEvent.setup();
    server.use(
      mockApi.post(API_ENDPOINTS.AUTH.RESET_PASSWORD, () =>
        errorResponse(400, "BAD_REQUEST", "Invalid or expired reset link")
      )
    );
    renderWithProviders(<App />, { authenticated: false, route: ROUTE });

    await user.type(await screen.findByLabelText("New password"), "password123");
    await user.type(screen.getByLabelText("Confirm new password"), "password123");
    await user.click(screen.getByRole("button", { name: "Update password" }));

    expect(await screen.findByText("Invalid or expired reset link")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a new one" })).toBeInTheDocument();
  });

  it("treats a missing token as an invalid link", async () => {
    const user = userEvent.setup();
    renderWithProviders(<App />, { authenticated: false, route: "/auth/reset-password" });

    expect(
      await screen.findByRole("heading", { name: "This link is not valid" })
    ).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Request a new link" }));
    expect(await screen.findByRole("heading", { name: "Reset your password" })).toBeInTheDocument();
  });
});
