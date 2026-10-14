import { HttpResponse } from "msw";

import { API_ENDPOINTS } from "@/shared/config/api-endpoints";

import { makeAuthOrganization, makeAuthTeam } from "../fixtures/organization";
import { makeAuthUser, makeTokens } from "../fixtures/user";
import { mockApi } from "../typed-http";

/** Resting-state auth handlers: every call succeeds. Suites testing failures `server.use` overrides. */
export const authHandlers = [
  mockApi.post(API_ENDPOINTS.AUTH.SIGNUP, async ({ request }) => {
    const body = await request.json(); // `SignUpIn`, from the spec — no cast
    return HttpResponse.json(
      {
        user: makeAuthUser({ email: body.email, fullName: body.fullName ?? null }),
        organization: makeAuthOrganization(),
        team: makeAuthTeam(),
        tokens: makeTokens(),
      },
      { status: 201 }
    );
  }),

  mockApi.post(API_ENDPOINTS.AUTH.SIGNIN, () => HttpResponse.json(makeTokens())),

  mockApi.post(API_ENDPOINTS.AUTH.REFRESH, () =>
    HttpResponse.json(
      makeTokens({ accessToken: "access-token-refreshed", refreshToken: "refresh-token-refreshed" })
    )
  ),

  mockApi.post(API_ENDPOINTS.AUTH.SIGNOUT, () => new HttpResponse(null, { status: 204 })),

  mockApi.post(API_ENDPOINTS.AUTH.FORGOT_PASSWORD, () => new HttpResponse(null, { status: 204 })),

  mockApi.post(API_ENDPOINTS.AUTH.RESET_PASSWORD, () => new HttpResponse(null, { status: 204 })),
];
