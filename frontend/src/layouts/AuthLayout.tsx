import { ErrorBoundary } from "react-error-boundary";
import { Link, Outlet, useLocation } from "react-router-dom";

import { RouteErrorFallback } from "@/shared/components/error-boundary";
import { APP_NAME } from "@/shared/constants/app";
import { ROUTES } from "@/shared/constants/routes";

/** Centered single-column shell for the guest-only auth pages. */
export default function AuthLayout() {
  const location = useLocation();

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-muted/40 p-6">
      <Link to={ROUTES.auth.login} className="mb-8 text-2xl font-semibold tracking-tight">
        {APP_NAME}
      </Link>
      <div className="w-full max-w-sm">
        <ErrorBoundary fallbackRender={RouteErrorFallback} resetKeys={[location.pathname]}>
          <Outlet />
        </ErrorBoundary>
      </div>
    </main>
  );
}
