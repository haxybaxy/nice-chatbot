import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/providers/use-auth";
import { Loading } from "@/shared/components/feedback";
import { ROUTES } from "@/shared/constants/routes";

interface GuestRouteProps {
  children: React.ReactNode;
}

/**
 * Guest-only route guard — the inverse of ProtectedRoute. Wraps auth pages (login /
 * sign-up) that an already-authenticated user should never see.
 *
 * It waits for the session-restore query to settle (`isLoading`) before deciding, so a
 * valid session recovered from the refresh token sends the user into the app instead of
 * flashing the login form and forcing a needless re-login.
 */
export function GuestRoute({ children }: GuestRouteProps) {
  const { user, isLoading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isLoading && user) {
      navigate(ROUTES.app.root, { replace: true });
    }
  }, [user, isLoading, navigate]);

  if (isLoading) {
    return <Loading fullHeight label="Loading…" />;
  }

  if (user) {
    return <Loading fullHeight label="Redirecting…" />;
  }

  return <>{children}</>;
}
