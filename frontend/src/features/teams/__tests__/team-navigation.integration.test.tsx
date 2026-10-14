import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import type { AddTeamMemberRequest, CreateTeamRequest, Team } from "@/features/teams/types";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { STORAGE_KEYS } from "@/shared/constants/storage-keys";
import { makeTeam, makeTeamMember } from "@/test/msw/fixtures/team";
import { TEAMS } from "@/test/msw/handlers/teams";
import { server } from "@/test/msw/server";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

describe("team context", () => {
  it("sends /app to the first team and remembers it", async () => {
    renderWithProviders(<App />, { route: "/app" });

    expect(await screen.findByRole("button", { name: "Team: General" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "New chat" })).toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEYS.LAST_TEAM_ID)).toBe(TEAMS.general.id);
  });

  it("sends /app to the remembered team", async () => {
    localStorage.setItem(STORAGE_KEYS.LAST_TEAM_ID, TEAMS.research.id);
    renderWithProviders(<App />, { route: "/app" });

    expect(await screen.findByRole("button", { name: "Team: Research" })).toBeInTheDocument();
  });

  it("redirects an unknown team id to a team the caller belongs to", async () => {
    renderWithProviders(<App />, { route: "/app/teams/not-mine/chat" });

    expect(await screen.findByRole("button", { name: "Team: General" })).toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEYS.LAST_TEAM_ID)).toBe(TEAMS.general.id);
  });

  it("switches teams from the sidebar and reloads that team's conversations", async () => {
    const user = userEvent.setup();
    const listedFor: string[] = [];
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATIONS, ({ params }) => {
        listedFor.push(params.team_id);
        return HttpResponse.json({ items: [] });
      })
    );
    renderWithProviders(<App />, { route: "/app/teams/team-1/chat" });

    await user.click(await screen.findByRole("button", { name: "Team: General" }));
    await user.click(await screen.findByRole("menuitem", { name: "Research" }));

    expect(await screen.findByRole("button", { name: "Team: Research" })).toBeInTheDocument();
    await waitFor(() => expect(listedFor).toEqual(["team-1", "team-2"]));
    expect(localStorage.getItem(STORAGE_KEYS.LAST_TEAM_ID)).toBe("team-2");
  });

  it("creates a team in the current organization and switches to it", async () => {
    const user = userEvent.setup();
    const bodies: CreateTeamRequest[] = [];
    let teams: Team[] = [TEAMS.general, TEAMS.research];
    server.use(
      mockApi.get(API_ENDPOINTS.TEAMS.MINE, () => HttpResponse.json(teams)),
      mockApi.post(API_ENDPOINTS.TEAMS.CREATE, async ({ request, params }) => {
        const body = await request.json();
        bodies.push(body);
        const team = makeTeam({
          id: "team-new",
          name: body.name,
          organizationId: params.organization_id,
        });
        teams = [...teams, team];
        return HttpResponse.json(team, { status: 201 });
      })
    );
    renderWithProviders(<App />, { route: "/app/teams/team-1/chat" });

    await user.click(await screen.findByRole("button", { name: "Team: General" }));
    await user.click(await screen.findByRole("menuitem", { name: "New team" }));
    const dialog = await screen.findByRole("dialog", { name: "New team" });
    await user.type(within(dialog).getByLabelText("Team name"), "Platform");
    await user.click(within(dialog).getByRole("button", { name: "Create team" }));

    expect(await screen.findByRole("button", { name: "Team: Platform" })).toBeInTheDocument();
    expect(bodies).toEqual([{ name: "Platform" }]);
  });

  it("lists, adds and removes members", async () => {
    const user = userEvent.setup();
    const added: AddTeamMemberRequest[] = [];
    const removed: string[] = [];
    let members = [
      makeTeamMember({
        teamId: "team-1",
        userId: "user-1",
        user: { id: "user-1", email: "user-1@example.com", fullName: "Test User" },
      }),
    ];
    server.use(
      mockApi.get(API_ENDPOINTS.TEAMS.MEMBERS, () => HttpResponse.json(members)),
      mockApi.post(API_ENDPOINTS.TEAMS.MEMBERS, async ({ request }) => {
        const body = await request.json();
        added.push(body);
        const member = makeTeamMember({
          teamId: "team-1",
          userId: "user-2",
          user: { id: "user-2", email: body.email, fullName: null },
        });
        members = [...members, member];
        return HttpResponse.json(member, { status: 201 });
      }),
      mockApi.delete(API_ENDPOINTS.TEAMS.MEMBER, ({ params }) => {
        removed.push(params.user_id);
        members = members.filter((member) => member.userId !== params.user_id);
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<App />, { route: "/app/teams/team-1/chat" });

    await user.click(await screen.findByRole("button", { name: "Team: General" }));
    await user.click(await screen.findByRole("menuitem", { name: "Members" }));
    const dialog = await screen.findByRole("dialog", { name: "Members of General" });
    expect(await within(dialog).findByText("Test User")).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText("Add a member by email"), "new@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Add member" }));
    expect(await within(dialog).findByText("new@example.com")).toBeInTheDocument();
    expect(added).toEqual([{ email: "new@example.com" }]);

    await user.click(within(dialog).getByRole("button", { name: "Remove new@example.com" }));
    await waitFor(() => expect(within(dialog).queryByText("new@example.com")).toBeNull());
    expect(removed).toEqual(["user-2"]);
  });
});
