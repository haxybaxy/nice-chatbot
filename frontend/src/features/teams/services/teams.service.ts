import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { apiClient } from "@/shared/services/api-client";

import type { AddTeamMemberRequest, CreateTeamRequest, Team, TeamMember } from "../types";

/** Teams service — the only module that talks to `/api/teams/*` and the organization's team route. */
class TeamsService {
  /** Every team the caller is a member of. */
  listMine(): Promise<Team[]> {
    return apiClient.get(API_ENDPOINTS.TEAMS.MINE);
  }

  /** Create a team in an organization; the caller becomes its first member. */
  create(organizationId: string, body: CreateTeamRequest): Promise<Team> {
    return apiClient.post(API_ENDPOINTS.TEAMS.CREATE, body, {
      path: { organization_id: organizationId },
    });
  }

  listMembers(teamId: string): Promise<TeamMember[]> {
    return apiClient.get(API_ENDPOINTS.TEAMS.MEMBERS, { path: { team_id: teamId } });
  }

  addMember(teamId: string, body: AddTeamMemberRequest): Promise<TeamMember> {
    return apiClient.post(API_ENDPOINTS.TEAMS.MEMBERS, body, { path: { team_id: teamId } });
  }

  async removeMember(teamId: string, userId: string): Promise<void> {
    await apiClient.delete(API_ENDPOINTS.TEAMS.MEMBER, {
      path: { team_id: teamId, user_id: userId },
    });
  }
}

export const teamsService = new TeamsService();
