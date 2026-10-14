/**
 * Teams types — aliases of the generated wire schemas (`Schema<"…">`), nothing hand-written.
 */
import type { Schema } from "@/shared/api/types";

/** A team the caller belongs to, with its organization (`TeamOut`). */
export type Team = Schema<"TeamOut">;

/** One membership row of a team (`TeamMemberOut`). */
export type TeamMember = Schema<"TeamMemberOut">;

/** `POST /api/organizations/{organization_id}/teams` body. */
export type CreateTeamRequest = Schema<"CreateTeamIn">;

/** `POST /api/teams/{team_id}/members` body: the member is looked up by email. */
export type AddTeamMemberRequest = Schema<"AddTeamMemberIn">;
