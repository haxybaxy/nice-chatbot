import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { AuthProvider } from "@/providers/auth-provider";
import { ThemeProvider } from "@/providers/theme-provider";
import { tokenStorage } from "@/shared/services/token-storage";

import { makeAccessToken } from "./msw/fixtures/user";

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

export interface RenderOpts extends Omit<RenderOptions, "wrapper"> {
  /**
   * Seed a valid (unexpired) access token + refresh token before rendering, so the session
   * query resolves to the mocked `/users/me` user. Default: true.
   */
  authenticated?: boolean;
  /** Initial router entry (defaults to "/"). */
  route?: string;
  /** Override the QueryClient (otherwise a fresh one is built). */
  queryClient?: QueryClient;
}

/**
 * Render a component inside the real provider tree (Query, Auth, Theme) with MSW available.
 * `apiClient` hits the MSW handlers, not the network.
 *
 * Production `Providers` is bypassed on purpose: it builds a QueryClient with retries +
 * staleTime, and tests need control over both.
 */
export function renderWithProviders(ui: ReactNode, opts: RenderOpts = {}) {
  const {
    authenticated = true,
    route = "/",
    queryClient = makeQueryClient(),
    ...renderOptions
  } = opts;

  if (authenticated) {
    tokenStorage.setTokens({
      accessToken: makeAccessToken(),
      refreshToken: "refresh-token-seed",
      expiresIn: 3600,
      tokenType: "bearer",
    });
  }

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>
          <AuthProvider>
            <ThemeProvider>{children}</ThemeProvider>
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  return { ...render(ui, { wrapper: Wrapper, ...renderOptions }), queryClient };
}
