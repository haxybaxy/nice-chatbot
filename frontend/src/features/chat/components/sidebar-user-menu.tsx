import { LogOutIcon, MonitorIcon, MoonIcon, SunIcon } from "lucide-react";

import { useSignOut } from "@/features/auth";
import { useAuth } from "@/providers/use-auth";
import { type Theme, useTheme } from "@/providers/use-theme";
import { Button } from "@/shared/components/ui/button";
import { SidebarMenu, SidebarMenuItem } from "@/shared/components/ui/sidebar";

const THEME_CYCLE: Record<Theme, Theme> = { light: "dark", dark: "system", system: "light" };
const THEME_ICON: Record<Theme, typeof SunIcon> = {
  light: SunIcon,
  dark: MoonIcon,
  system: MonitorIcon,
};

/** The sidebar footer: who is signed in, the theme toggle and sign out. */
export function SidebarUserMenu() {
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();
  const signOut = useSignOut();
  const ThemeIcon = THEME_ICON[theme];

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <div className="flex items-center gap-1 px-2 py-1 text-sm">
          <span className="min-w-0 flex-1 truncate text-muted-foreground" title={user?.email}>
            {user?.email}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={`Theme: ${theme}`}
            onClick={() => setTheme(THEME_CYCLE[theme])}
          >
            <ThemeIcon />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Sign out"
            onClick={() => signOut.mutate()}
            disabled={signOut.isPending}
          >
            <LogOutIcon />
          </Button>
        </div>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
