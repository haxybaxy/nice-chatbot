import { Link } from "react-router-dom";

import { Button } from "@/shared/components/ui/button";
import { ROUTES } from "@/shared/constants/routes";

import { AuthCard } from "./auth-card";

/** `/auth/reset-password` opened without a usable `?token=`: nothing to submit, so offer a new link. */
export function InvalidResetLink() {
  return (
    <AuthCard
      title="This link is not valid"
      description="Reset links work once and expire after 30 minutes."
    >
      <Button asChild className="w-full">
        <Link to={ROUTES.auth.forgotPassword}>Request a new link</Link>
      </Button>
    </AuthCard>
  );
}
