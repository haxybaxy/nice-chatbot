import { HttpResponse } from "msw";

import { API_ENDPOINTS } from "@/shared/config/api-endpoints";

import { makeTeam, makeTeamMember } from "../fixtures/team";
import { mockApi } from "../typed-http";

/** The resting teams: `/app` opens `general` unless `LAST_TEAM_ID` says otherwise. */
export const TEAMS = {
  general: makeTeam({ id: "team-1", name: "General" }),
  research: makeTeam({ id: "team-2", name: "Research" }),
};

export const teamsHandlers = [
  mockApi.get(API_ENDPOINTS.TEAMS.MINE, () => HttpResponse.json([TEAMS.general, TEAMS.research])),

  mockApi.post(API_ENDPOINTS.TEAMS.CREATE, async ({ request, params }) => {
    const body = await request.json(); // `CreateTeamIn`, from the spec — no cast
    return HttpResponse.json(
      makeTeam({ id: "team-new", name: body.name, organizationId: params.organization_id }),
      { status: 201 }
    );
  }),

  mockApi.get(API_ENDPOINTS.TEAMS.TEAM, ({ params }) =>
    HttpResponse.json(makeTeam({ id: params.team_id }))
  ),

  mockApi.get(API_ENDPOINTS.TEAMS.MEMBERS, ({ params }) =>
    HttpResponse.json([
      makeTeamMember({
        teamId: params.team_id,
        userId: "user-1",
        user: { id: "user-1", email: "user-1@example.com", fullName: "Test User" },
      }),
    ])
  ),

  mockApi.post(API_ENDPOINTS.TEAMS.MEMBERS, async ({ request, params }) => {
    const body = await request.json(); // `AddTeamMemberIn`
    return HttpResponse.json(
      makeTeamMember({
        teamId: params.team_id,
        userId: "user-9",
        user: { id: "user-9", email: body.email, fullName: null },
      }),
      { status: 201 }
    );
  }),

  mockApi.delete(API_ENDPOINTS.TEAMS.MEMBER, () => new HttpResponse(null, { status: 204 })),
];
