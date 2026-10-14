import { LogOut } from "lucide-react";
import { ErrorBoundary } from "react-error-boundary";
import { Link, Outlet, useLocation } from "react-router-dom";

import { ProtectedRoute, useSignOut } from "@/features/auth";
import { useAuth } from "@/providers/use-auth";
import { RouteErrorFallback } from "@/shared/components/error-boundary";
import { Button } from "@/shared/components/ui/button";
import { APP_NAME } from "@/shared/constants/app";
import { ROUTES } from "@/shared/constants/routes";

function AppHeader() {
  const { user } = useAuth();
  const signOut = useSignOut();

  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between px-4 sm:px-6">
        <Link to={ROUTES.app.root} className="font-semibold tracking-tight">
          {APP_NAME}
        </Link>
        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-muted-foreground sm:inline">{user?.email}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => signOut.mutate()}
            disabled={signOut.isPending}
          >
            <LogOut />
            Sign out
          </Button>
        </div>
      </div>
    </header>
  );
}

/**
 * The app shell for signed-in users. App-level, cross-route hooks belong here rather than
 * in pages, because pages unmount on navigation while these flows keep running.
 */
export default function ProtectedLayout() {
  const location = useLocation();
  const routeResetKey = `${location.pathname}${location.search}${location.hash}`;

  return (
    <ProtectedRoute>
      <div className="flex min-h-screen flex-col bg-background">
        <AppHeader />
        <main className="mx-auto w-full max-w-5xl flex-1 p-4 sm:p-6">
          <ErrorBoundary fallbackRender={RouteErrorFallback} resetKeys={[routeResetKey]}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </ProtectedRoute>
  );
}
