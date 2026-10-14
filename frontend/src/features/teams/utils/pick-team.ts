import type { Team } from "../types";

/** The team `/app` opens: the remembered one while it is still among the caller's teams, else the first. */
export function pickTeam(teams: readonly Team[], lastTeamId: string | null): Team | null {
  return teams.find((team) => team.id === lastTeamId) ?? teams[0] ?? null;
}
