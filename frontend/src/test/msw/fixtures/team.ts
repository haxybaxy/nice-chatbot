import type { Team, TeamMember } from "@/features/teams/types";

let counter = 1;

const NOW = "2026-01-01T00:00:00Z";

/** A team the caller belongs to (`TeamOut`), in the test organization. */
export function makeTeam(overrides: Partial<Team> = {}): Team {
  const id = overrides.id ?? `team-${counter++}`;
  return {
    id,
    name: `Team ${id}`,
    organizationId: "organization-1",
    organization: { id: "organization-1", name: "Test User's organization" },
    createdBy: "user-1",
    createdAt: NOW,
    updatedAt: NOW,
    ...overrides,
  };
}

/** One membership row (`TeamMemberOut`). */
export function makeTeamMember(overrides: Partial<TeamMember> = {}): TeamMember {
  const userId = overrides.userId ?? `user-${counter++}`;
  return {
    teamId: "team-1",
    userId,
    createdAt: NOW,
    user: { id: userId, email: `${userId}@example.com`, fullName: "Team Mate" },
    ...overrides,
  };
}
