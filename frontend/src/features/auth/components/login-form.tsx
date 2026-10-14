import { Link } from "react-router-dom";

import { revalidateLogic, submitMutation, useAppForm } from "@/shared/components/form";
import { FormAlert } from "@/shared/components/form/form-alert";
import { ROUTES } from "@/shared/constants/routes";

import { AuthCard } from "./auth-card";
import { useSignIn } from "../hooks/use-auth";
import { signInSchema } from "../schemas/auth-form.schemas";
import type { SignInCredentials } from "../types";

const linkClassName = "text-foreground underline underline-offset-4";

export function LoginForm() {
  const signIn = useSignIn();
  const form = useAppForm({
    defaultValues: { email: "", password: "" },
    validationLogic: revalidateLogic(),
    validators: { onDynamic: signInSchema },
    onSubmit: submitMutation((value: SignInCredentials) => signIn.mutateAsync(value)),
  });

  return (
    <AuthCard title="Sign in" description="Enter your email and password to continue.">
      <form.AppForm>
        <form.Root>
          <form.AppField name="email">
            {(field) => <field.TextField label="Email" type="email" autoComplete="email" />}
          </form.AppField>
          <form.AppField name="password">
            {(field) => (
              <field.TextField label="Password" type="password" autoComplete="current-password" />
            )}
          </form.AppField>

          <FormAlert error={signIn.error} />

          <form.SubmitButton pendingLabel="Signing in…">Sign in</form.SubmitButton>

          <p className="text-center text-sm text-muted-foreground">
            <Link to={ROUTES.auth.forgotPassword} className={linkClassName}>
              Forgot your password?
            </Link>
          </p>
          <p className="text-center text-sm text-muted-foreground">
            No account yet?{" "}
            <Link to={ROUTES.auth.signUp} className={linkClassName}>
              Create one
            </Link>
          </p>
        </form.Root>
      </form.AppForm>
    </AuthCard>
  );
}
