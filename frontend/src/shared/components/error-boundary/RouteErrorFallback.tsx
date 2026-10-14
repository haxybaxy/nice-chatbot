import { AlertTriangle, Home, RotateCcw } from "lucide-react";
import type { FallbackProps } from "react-error-boundary";

import { Button } from "@/shared/components/ui/button";
import { ROUTES } from "@/shared/constants/routes";

export function RouteErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  const err = error instanceof Error ? error : new Error(String(error));

  return (
    <div role="alert" className="flex min-h-[50vh] items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6 text-center">
        <div className="flex justify-center">
          <AlertTriangle className="h-12 w-12 text-destructive" />
        </div>

        <div className="space-y-2">
          <h2 className="text-xl font-semibold text-foreground">Something went wrong</h2>
          <p className="text-sm text-muted-foreground">
            This page hit an error. You can try again or go back to the home page.
          </p>
        </div>

        {import.meta.env.DEV && (
          <pre className="max-h-40 overflow-auto rounded-lg bg-destructive/10 p-4 text-left text-xs text-destructive">
            {err.message}
            {err.stack && `\n\n${err.stack}`}
          </pre>
        )}

        <div className="flex justify-center gap-3">
          <Button variant="default" size="sm" onClick={resetErrorBoundary}>
            <RotateCcw />
            Try again
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              resetErrorBoundary();
              window.location.href = ROUTES.app.root;
            }}
          >
            <Home />
            Go home
          </Button>
        </div>
      </div>
    </div>
  );
}
