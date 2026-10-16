import { ChevronsUpDownIcon, LogOutIcon, MonitorIcon, MoonIcon, SunIcon } from "lucide-react";

import { useSignOut } from "@/features/auth";
import { useAuth } from "@/providers/use-auth";
import { type Theme, useTheme } from "@/providers/use-theme";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/shared/components/ui/sidebar";

const THEMES: readonly { theme: Theme; label: string; icon: typeof SunIcon }[] = [
  { theme: "light", label: "Light", icon: SunIcon },
  { theme: "dark", label: "Dark", icon: MoonIcon },
  { theme: "system", label: "System", icon: MonitorIcon },
];

/**
 * The sidebar footer, as ChatGPT's: the account row (initial, email) opening a menu with the
 * theme and Sign out — one place for everything about the signed-in user.
 */
export function SidebarUserMenu() {
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();
  const signOut = useSignOut();
  const email = user?.email ?? "";

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg" aria-label={`Account: ${email}`}>
              <span
                aria-hidden="true"
                className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-primary text-sm font-medium text-sidebar-primary-foreground uppercase"
              >
                {email.charAt(0) || "?"}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm">{email}</span>
              <ChevronsUpDownIcon className="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="min-w-56" side="top" align="start">
            <DropdownMenuLabel className="truncate font-normal text-muted-foreground">
              {email}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Theme</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={theme}>
              {THEMES.map(({ theme: option, label, icon: Icon }) => (
                <DropdownMenuRadioItem
                  key={option}
                  value={option}
                  onSelect={() => setTheme(option)}
                >
                  <Icon />
                  {label}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => signOut.mutate()} disabled={signOut.isPending}>
              <LogOutIcon />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
