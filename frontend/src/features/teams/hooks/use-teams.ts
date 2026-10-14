import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { QUERY_KEYS } from "@/shared/constants/query-keys";

import { teamsService } from "../services/teams.service";

/** The caller's teams (`GET /api/teams`). Changes rarely: a sign-up or a create invalidates it. */
export function useMyTeams() {
  return useQuery({
    queryKey: QUERY_KEYS.teams.mine,
    queryFn: () => teamsService.listMine(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreateTeam() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ organizationId, name }: { organizationId: string; name: string }) =>
      teamsService.create(organizationId, { name }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEYS.teams.all }),
  });
}

export function useTeamMembers(teamId: string) {
  return useQuery({
    queryKey: QUERY_KEYS.teams.members(teamId),
    queryFn: () => teamsService.listMembers(teamId),
  });
}

export function useAddTeamMember() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ teamId, email }: { teamId: string; email: string }) =>
      teamsService.addMember(teamId, { email }),
    onSuccess: (_, { teamId }) =>
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.teams.members(teamId) }),
  });
}

export function useRemoveTeamMember() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ teamId, userId }: { teamId: string; userId: string }) =>
      teamsService.removeMember(teamId, userId),
    onSuccess: (_, { teamId }) =>
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.teams.members(teamId) }),
  });
}
