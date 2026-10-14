import { Link } from "react-router-dom";

import { revalidateLogic, submitMutation, useAppForm } from "@/shared/components/form";
import { FormAlert } from "@/shared/components/form/form-alert";
import { Button } from "@/shared/components/ui/button";
import { ROUTES } from "@/shared/constants/routes";

import { AuthCard } from "./auth-card";
import { useResetPassword } from "../hooks/use-auth";
import { resetPasswordSchema, type ResetPasswordFormData } from "../schemas/auth-form.schemas";

interface ResetPasswordFormProps {
  /** The raw token from the mailed link (`?token=…`), already checked for shape by the page. */
  token: string;
}

export function ResetPasswordForm({ token }: ResetPasswordFormProps) {
  const reset = useResetPassword();
  const form = useAppForm({
    // `token` has no input: it travels with the values so the schema can require it.
    defaultValues: { token, password: "", confirmPassword: "" },
    validationLogic: revalidateLogic(),
    validators: { onDynamic: resetPasswordSchema },
    // Only the wire fields: the backend rejects unknown keys (`extra="forbid"`).
    onSubmit: submitMutation((value: ResetPasswordFormData) =>
      reset.mutateAsync({ token: value.token, password: value.password })
    ),
  });

  if (reset.isSuccess) {
    return (
      <AuthCard title="Password updated" description="Sign in with your new password.">
        <Button asChild className="w-full">
          <Link to={ROUTES.auth.login}>Sign in</Link>
        </Button>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Choose a new password" description="It must be at least 8 characters.">
      <form.AppForm>
        <form.Root>
          <form.AppField name="password">
            {(field) => (
              <field.TextField label="New password" type="password" autoComplete="new-password" />
            )}
          </form.AppField>
          <form.AppField name="confirmPassword">
            {(field) => (
              <field.TextField
                label="Confirm new password"
                type="password"
                autoComplete="new-password"
              />
            )}
          </form.AppField>

          <FormAlert error={reset.error} />

          <form.SubmitButton pendingLabel="Updating…">Update password</form.SubmitButton>

          <p className="text-center text-sm text-muted-foreground">
            Link expired?{" "}
            <Link
              to={ROUTES.auth.forgotPassword}
              className="text-foreground underline underline-offset-4"
            >
              Request a new one
            </Link>
          </p>
        </form.Root>
      </form.AppForm>
    </AuthCard>
  );
}
