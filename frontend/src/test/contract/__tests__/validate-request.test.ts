import { describe, expect, it } from "vitest";

import { validateQueryParams, validateRequest, validateResponse } from "../validate-request";

describe("contract validator (against the vendored backend spec)", () => {
  it("accepts a well-formed sign-up body", () => {
    expect(
      validateRequest("POST", "/api/auth/signup", {
        email: "a@example.com",
        password: "password123",
        fullName: null,
      })
    ).toBeNull();
  });

  it("rejects a body field the backend forbids", () => {
    const violation = validateRequest("POST", "/api/auth/signup", {
      email: "a@example.com",
      password: "password123",
      confirmPassword: "password123",
    });

    expect(violation?.kind).toBe("body");
    expect(violation?.errors.map((e) => e.field)).toContain("confirmPassword");
  });

  it("rejects an undeclared query parameter", () => {
    const violation = validateQueryParams(
      "GET",
      "/api/users/me",
      new URLSearchParams({ include: "memberships" })
    );

    expect(violation?.kind).toBe("query");
  });

  it("rejects a mocked response that omits a required field", () => {
    const violation = validateResponse("GET", "/api/users/me", 200, {
      id: "user-1",
      email: "a@example.com",
      createdAt: "2026-01-01T00:00:00Z",
    });

    expect(violation?.kind).toBe("response");
    expect(violation?.errors.map((e) => e.field)).toContain("updatedAt");
  });

  it("ignores paths the spec does not declare", () => {
    expect(validateRequest("POST", "/api/unknown", { anything: 1 })).toBeNull();
    expect(validateResponse("GET", "/api/unknown", 200, { anything: 1 })).toBeNull();
  });
});
