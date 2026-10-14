import { useEffect, useMemo, useState } from "react";

import { STORAGE_KEYS } from "@/shared/constants/storage-keys";
import { storage } from "@/shared/services/local-storage";

import { type Theme, ThemeProviderContext } from "./use-theme";

type ThemeProviderProps = {
  children: React.ReactNode;
  defaultTheme?: Theme;
  enableSystem?: boolean;
};

const THEMES: readonly Theme[] = ["light", "dark", "system"];

function readStoredTheme(): Theme | null {
  const stored = storage.getString(STORAGE_KEYS.THEME);
  return THEMES.find((theme) => theme === stored) ?? null;
}

function resolveTheme(theme: Theme, enableSystem: boolean): "light" | "dark" {
  if (theme !== "system") return theme;
  if (!enableSystem) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Applies the `.dark` class Tailwind's `dark:` variant keys off (see globals.css) and persists the choice. */
export function ThemeProvider({
  children,
  defaultTheme = "system",
  enableSystem = true,
}: ThemeProviderProps) {
  // Lazily seeded from storage: this is a client-only SPA, so there is no hydration mismatch
  // to defer for.
  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme() ?? defaultTheme);

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(resolveTheme(theme, enableSystem));
  }, [theme, enableSystem]);

  const value = useMemo(
    () => ({
      theme,
      setTheme: (next: Theme) => {
        storage.setString(STORAGE_KEYS.THEME, next);
        setThemeState(next);
      },
    }),
    [theme]
  );

  return <ThemeProviderContext.Provider value={value}>{children}</ThemeProviderContext.Provider>;
}
