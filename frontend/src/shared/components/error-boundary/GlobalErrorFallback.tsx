import type { FallbackProps } from "react-error-boundary";

export function GlobalErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  const err = error instanceof Error ? error : new Error(String(error));

  return (
    <div
      role="alert"
      className="min-h-screen flex items-center justify-center bg-white dark:bg-zinc-950 p-6"
    >
      <div className="max-w-md w-full text-center space-y-6">
        <div className="flex justify-center">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="48"
            height="48"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-red-500"
          >
            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />
            <path d="M12 9v4" />
            <path d="M12 17h.01" />
          </svg>
        </div>

        <div className="space-y-2">
          <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">
            Something went wrong
          </h1>
          <p className="text-zinc-500 dark:text-zinc-400">
            An unexpected error occurred. Please try reloading the page.
          </p>
        </div>

        {import.meta.env.DEV && (
          <pre className="text-left text-xs bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-400 p-4 rounded-lg overflow-auto max-h-40">
            {err.message}
            {err.stack && `\n\n${err.stack}`}
          </pre>
        )}

        <div className="flex justify-center gap-3">
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Reload Page
          </button>
          <button
            onClick={() => {
              resetErrorBoundary();
              window.location.href = import.meta.env.BASE_URL;
            }}
            className="px-4 py-2 border border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 rounded-lg text-sm font-medium hover:bg-zinc-50 dark:hover:bg-zinc-900 transition-colors"
          >
            Go to Home
          </button>
        </div>
      </div>
    </div>
  );
}
