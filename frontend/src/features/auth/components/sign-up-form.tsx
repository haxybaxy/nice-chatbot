import { Link } from "react-router-dom";

import { revalidateLogic, submitMutation, useAppForm } from "@/shared/components/form";
import { FormAlert } from "@/shared/components/form/form-alert";
import { ROUTES } from "@/shared/constants/routes";

import { AuthCard } from "./auth-card";
import { useSignUp } from "../hooks/use-auth";
import { signUpSchema, type SignUpFormData } from "../schemas/auth-form.schemas";

export function SignUpForm() {
  const signUp = useSignUp();
  const form = useAppForm({
    defaultValues: { fullName: "", email: "", password: "", confirmPassword: "" },
    validationLogic: revalidateLogic(),
    validators: { onDynamic: signUpSchema },
    // Only the wire fields: the backend rejects unknown keys (`extra="forbid"`), and an
    // empty name must travel as null (`fullName` has min_length=1 when present).
    onSubmit: submitMutation(({ fullName, email, password }: SignUpFormData) =>
      signUp.mutateAsync({ email, password, fullName: fullName || null })
    ),
  });

  return (
    <AuthCard
      title="Create your account"
      description="You will be signed in as soon as the account exists."
    >
      <form.AppForm>
        <form.Root>
          <form.AppField name="fullName">
            {(field) => <field.TextField label="Full name (optional)" autoComplete="name" />}
          </form.AppField>
          <form.AppField name="email">
            {(field) => <field.TextField label="Email" type="email" autoComplete="email" />}
          </form.AppField>
          <form.AppField name="password">
            {(field) => (
              <field.TextField label="Password" type="password" autoComplete="new-password" />
            )}
          </form.AppField>
          <form.AppField name="confirmPassword">
            {(field) => (
              <field.TextField
                label="Confirm password"
                type="password"
                autoComplete="new-password"
              />
            )}
          </form.AppField>

          <FormAlert error={signUp.error} />

          <form.SubmitButton pendingLabel="Creating account…">Create account</form.SubmitButton>

          <p className="text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link to={ROUTES.auth.login} className="text-foreground underline underline-offset-4">
              Sign in
            </Link>
          </p>
        </form.Root>
      </form.AppForm>
    </AuthCard>
  );
}
