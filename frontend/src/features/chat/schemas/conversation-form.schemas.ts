import { z } from "zod";

/**
 * Form-only validation for the rename dialog, mirroring `UpdateConversationIn.title`
 * (1–255 chars). Guarded by `src/test/guards/form-schemas.guard.test.ts`.
 */
export const renameConversationSchema = z.object({
  title: z.string().trim().min(1, "Enter a title").max(255, "Title must be at most 255 characters"),
});

export type RenameConversationFormData = z.infer<typeof renameConversationSchema>;
