import { Toaster } from "@/shared/components/ui/sonner";

import { useTheme } from "./use-theme";

/** The shadcn `Toaster`, themed from our ThemeProvider. Rendered once, in `Providers`. */
export function AppToaster() {
  const { theme } = useTheme();
  return <Toaster theme={theme} />;
}
