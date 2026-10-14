import { z } from "zod";

/**
 * Form-only validation (TanStack Form `onDynamic`), mirroring the structural bounds of
 * `CreateTeamIn` (name 1–255) and `AddTeamMemberIn` (an email). Guarded by
 * `src/test/guards/form-schemas.guard.test.ts` against the spec.
 */

export const createTeamSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Enter a team name")
    .max(255, "Name must be at most 255 characters"),
});

export const addTeamMemberSchema = z.object({
  email: z.email("Enter a valid email address"),
});
