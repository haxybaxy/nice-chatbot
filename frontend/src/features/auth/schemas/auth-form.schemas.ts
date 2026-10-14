import { z } from "zod";

/**
 * Form-only validation, run by TanStack Form as the form-level `onDynamic` validator (a zod
 * schema is a Standard Schema; its issues land on the field named by their path). These mirror
 * the backend's structural rules (`SignInIn` / `SignUpIn` / `ForgotPasswordIn` /
 * `ResetPasswordIn`: password 8–256 chars, name ≤ 255, token 1–128) so obvious mistakes are
 * caught before a round-trip; `src/test/guards/form-schemas.guard.test.ts` fails when a bound
 * here drifts from the spec. The real password policy is enforced by the Cognito pool; its
 * rejection comes back as the error envelope's `error` message and is shown verbatim.
 */

const email = z.email("Enter a valid email address");

/** A new password and its confirmation: sign-up and reset share the rule and the messages. */
const newPassword = {
  password: z
    .string()
    .min(8, "Password must be at least 8 characters")
    .max(256, "Password must be at most 256 characters"),
  confirmPassword: z.string().min(1, "Confirm your password"),
};

const passwordsMatch = (data: { password: string; confirmPassword: string }) =>
  data.password === data.confirmPassword;
const passwordsMatchParams = { message: "Passwords do not match", path: ["confirmPassword"] };

export const signInSchema = z.object({
  email,
  password: z
    .string()
    .min(1, "Password is required")
    .max(256, "Password must be at most 256 characters"),
});

export const signUpSchema = z
  .object({
    fullName: z.string().trim().max(255, "Name must be at most 255 characters"),
    email,
    ...newPassword,
  })
  .refine(passwordsMatch, passwordsMatchParams);

export type SignUpFormData = z.infer<typeof signUpSchema>;

export const forgotPasswordSchema = z.object({ email });

/** The raw token from the mailed link — also what the reset page checks before showing the form. */
export const resetTokenSchema = z.string().min(1).max(128);

export const resetPasswordSchema = z
  .object({
    // Supplied by the page from `?token=`, not typed by the user; here so the wire's required
    // field is part of the validated values.
    token: resetTokenSchema,
    ...newPassword,
  })
  .refine(passwordsMatch, passwordsMatchParams);

export type ResetPasswordFormData = z.infer<typeof resetPasswordSchema>;
