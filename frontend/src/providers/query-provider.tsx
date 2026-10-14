import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useEffect, useState } from "react";

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [showDevtools, setShowDevtools] = useState(false);

  useEffect(() => {
    const win = window as Window & { toggleDevtools?: () => void };
    win.toggleDevtools = () => {
      setShowDevtools((prev) => !prev);
    };
    return () => {
      delete win.toggleDevtools;
    };
  }, []);

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1 minute
            gcTime: 5 * 60 * 1000, // 5 minutes
            retry: (failureCount, error) => {
              // Don't retry on 4xx errors except 408 (timeout)
              if (error instanceof Error && "status" in error) {
                const status = error.status as number;
                if (status >= 400 && status < 500 && status !== 408) {
                  return false;
                }
              }
              return failureCount < 3;
            },
          },
          mutations: {
            retry: false,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {showDevtools && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  );
}
