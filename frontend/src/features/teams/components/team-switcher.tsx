import { CheckIcon, ChevronsUpDownIcon, PlusIcon, UsersIcon } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/shared/components/ui/sidebar";
import { ROUTES } from "@/shared/constants/routes";

import { CreateTeamDialog } from "./create-team-dialog";
import { TeamMembersDialog } from "./team-members-dialog";
import { useMyTeams } from "../hooks/use-teams";
import type { Team } from "../types";

type TeamDialog = "create" | "members" | null;

/**
 * The sidebar's team menu: the current team, the caller's other teams (switching navigates to
 * that team's chat), the members dialog and "New team". Lives inside a `SidebarProvider`.
 */
export function TeamSwitcher({ currentTeam }: { currentTeam: Team }) {
  const teams = useMyTeams();
  const navigate = useNavigate();
  const [dialog, setDialog] = useState<TeamDialog>(null);
  const closeDialog = (open: boolean) => {
    if (!open) setDialog(null);
  };

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg" aria-label={`Team: ${currentTeam.name}`}>
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                <UsersIcon className="size-4" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">{currentTeam.name}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {currentTeam.organization.name}
                </span>
              </div>
              <ChevronsUpDownIcon className="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="min-w-56" align="start" side="bottom">
            <DropdownMenuLabel>Teams</DropdownMenuLabel>
            {(teams.data ?? []).map((team) => (
              <DropdownMenuItem
                key={team.id}
                onSelect={() => navigate(ROUTES.app.teamChat(team.id))}
              >
                <span className="truncate">{team.name}</span>
                {team.id === currentTeam.id && <CheckIcon className="ml-auto size-4" />}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => setDialog("members")}>
              <UsersIcon />
              Members
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setDialog("create")}>
              <PlusIcon />
              New team
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <CreateTeamDialog
          organizationId={currentTeam.organizationId}
          open={dialog === "create"}
          onOpenChange={closeDialog}
        />
        <TeamMembersDialog
          team={currentTeam}
          open={dialog === "members"}
          onOpenChange={closeDialog}
        />
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
