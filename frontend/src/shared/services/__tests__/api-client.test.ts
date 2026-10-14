import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiClient } from "@/shared/services/api-client";
import { server } from "@/test/msw/server";
import { mockApi } from "@/test/msw/typed-http";

describe("apiClient path parameters", () => {
  it("substitutes and URL-encodes `{segments}` from options.path", async () => {
    let pathname = "";
    server.use(
      mockApi.get("/api/organizations/{organization_id}", ({ request }) => {
        pathname = new URL(request.url).pathname;
        // Checked against `OrganizationOut` by the resolver's type and by the runtime validator.
        return HttpResponse.json({
          id: "org-1",
          name: "Acme",
          createdAt: "2026-01-01T00:00:00Z",
          updatedAt: "2026-01-01T00:00:00Z",
        });
      })
    );

    const organization = await apiClient.get("/api/organizations/{organization_id}", {
      path: { organization_id: "org 1/x" },
    });

    expect(pathname).toBe("/api/organizations/org%201%2Fx");
    expect(organization.name).toBe("Acme");
  });
});
