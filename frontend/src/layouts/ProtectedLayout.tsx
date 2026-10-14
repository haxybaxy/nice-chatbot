import { ErrorBoundary } from "react-error-boundary";
import { Outlet, useLocation } from "react-router-dom";

import { ProtectedRoute } from "@/features/auth";
import { RouteErrorFallback } from "@/shared/components/error-boundary";

/**
 * The gate for signed-in routes: a bare shell with no chrome of its own. The chat shell
 * (`ChatLayout`, nested under `/app/teams/:teamId`) owns the sidebar and the header. App-level,
 * cross-route hooks belong here rather than in pages, because pages unmount on navigation
 * while these flows keep running.
 */
export default function ProtectedLayout() {
  const location = useLocation();
  const routeResetKey = `${location.pathname}${location.search}${location.hash}`;

  return (
    <ProtectedRoute>
      <ErrorBoundary fallbackRender={RouteErrorFallback} resetKeys={[routeResetKey]}>
        <Outlet />
      </ErrorBoundary>
    </ProtectedRoute>
  );
}
