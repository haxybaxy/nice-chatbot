import { AuthProvider } from "./auth-provider";
import { QueryProvider } from "./query-provider";
import { ThemeProvider } from "./theme-provider";
import { AppToaster } from "./toaster";

/** Provider hierarchy — order matters: Query → Auth → Theme. */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryProvider>
      <AuthProvider>
        <ThemeProvider defaultTheme="system" enableSystem>
          {children}
          <AppToaster />
        </ThemeProvider>
      </AuthProvider>
    </QueryProvider>
  );
}
