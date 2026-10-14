import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/providers/use-auth";
import { Loading } from "@/shared/components/feedback";
import { ROUTES } from "@/shared/constants/routes";

interface ProtectedRouteProps {
  children: React.ReactNode;
}

/**
 * Route guard for the app. Waits for the session-restore query to settle before deciding,
 * so a reload with a valid refresh token lands on the page instead of the login form.
 */
export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { user, isLoading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isLoading && !user) {
      navigate(ROUTES.auth.login, { replace: true });
    }
  }, [user, isLoading, navigate]);

  if (isLoading) {
    return <Loading fullHeight label="Loading…" />;
  }

  if (!user) {
    return <Loading fullHeight label="Redirecting…" />;
  }

  return <>{children}</>;
}
