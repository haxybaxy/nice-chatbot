import type { AuthOrganization, AuthTeam } from "@/features/auth/types";

let counter = 1;

/** The personal organization sign-up creates for the new user (`AuthOrganizationOut`). */
export function makeAuthOrganization(overrides: Partial<AuthOrganization> = {}): AuthOrganization {
  const id = overrides.id ?? `organization-${counter++}`;
  return { id, name: "Test User's organization", ...overrides };
}

/** The default team sign-up creates in that organization (`AuthTeamOut`). */
export function makeAuthTeam(overrides: Partial<AuthTeam> = {}): AuthTeam {
  const id = overrides.id ?? `team-${counter++}`;
  return { id, name: "General", ...overrides };
}
