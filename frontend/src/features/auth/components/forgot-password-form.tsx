import { Link } from "react-router-dom";

import { revalidateLogic, submitMutation, useAppForm } from "@/shared/components/form";
import { FormAlert } from "@/shared/components/form/form-alert";
import { ROUTES } from "@/shared/constants/routes";

import { AuthCard } from "./auth-card";
import { useForgotPassword } from "../hooks/use-auth";
import { forgotPasswordSchema } from "../schemas/auth-form.schemas";
import type { ForgotPasswordRequest } from "../types";

const linkClassName = "text-foreground underline underline-offset-4";

export function ForgotPasswordForm() {
  const forgot = useForgotPassword();
  const form = useAppForm({
    defaultValues: { email: "" },
    validationLogic: revalidateLogic(),
    validators: { onDynamic: forgotPasswordSchema },
    onSubmit: submitMutation((value: ForgotPasswordRequest) => forgot.mutateAsync(value)),
  });

  if (forgot.isSuccess) {
    // The backend answers 204 whether or not the address has an account, so neither do we.
    return (
      <AuthCard
        title="Check your inbox"
        description={`If an account exists for ${forgot.variables.email}, a reset link is on its way. It works once and expires in 30 minutes.`}
      >
        <p className="text-center text-sm text-muted-foreground">
          <Link to={ROUTES.auth.login} className={linkClassName}>
            Back to sign in
          </Link>
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Reset your password"
      description="Enter your email and we will send you a link to choose a new one."
    >
      <form.AppForm>
        <form.Root>
          <form.AppField name="email">
            {(field) => <field.TextField label="Email" type="email" autoComplete="email" />}
          </form.AppField>

          <FormAlert error={forgot.error} />

          <form.SubmitButton pendingLabel="Sending…">Send reset link</form.SubmitButton>

          <p className="text-center text-sm text-muted-foreground">
            Remembered it?{" "}
            <Link to={ROUTES.auth.login} className={linkClassName}>
              Sign in
            </Link>
          </p>
        </form.Root>
      </form.AppForm>
    </AuthCard>
  );
}
