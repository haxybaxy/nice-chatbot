import { useSearchParams } from "react-router-dom";

import { InvalidResetLink } from "../components/invalid-reset-link";
import { ResetPasswordForm } from "../components/reset-password-form";
import { resetTokenSchema } from "../schemas/auth-form.schemas";

/** The page the reset mail links to: `/auth/reset-password?token=…`. */
export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";

  if (!resetTokenSchema.safeParse(token).success) {
    return <InvalidResetLink />;
  }
  return <ResetPasswordForm token={token} />;
}
