import { Outlet } from "react-router-dom";

import { ChatSidebar } from "@/features/chat";
import { useCurrentTeam } from "@/features/teams";
import { Loading } from "@/shared/components/feedback";
import { Alert, AlertDescription } from "@/shared/components/ui/alert";
import { SidebarInset, SidebarProvider } from "@/shared/components/ui/sidebar";
import { TooltipProvider } from "@/shared/components/ui/tooltip";

/**
 * The team-scoped chat shell under `/app/teams/:teamId`: validates the team (redirecting an
 * unknown id to the remembered or first team, see `useCurrentTeam`), then renders the sidebar
 * and a full-height inset for the thread.
 */
export default function ChatLayout() {
  const { team, teams, isPending, error } = useCurrentTeam();

  if (isPending) {
    return <Loading fullHeight label="Loading your teams…" />;
  }
  if (error) {
    return (
      <div className="mx-auto max-w-md p-6">
        <Alert variant="destructive">
          <AlertDescription>Could not load your teams: {error.message}</AlertDescription>
        </Alert>
      </div>
    );
  }
  if (!team) {
    return teams.length === 0 ? (
      <div className="mx-auto max-w-md p-6 text-center text-sm text-muted-foreground">
        You are not a member of any team yet. Ask a team member to add you.
      </div>
    ) : (
      <Loading fullHeight label="Redirecting…" />
    );
  }

  // shadcn 4's `Tooltip` no longer provides for itself and the sidebar's menu buttons render one.
  return (
    <TooltipProvider>
      <SidebarProvider>
        <ChatSidebar team={team} />
        <SidebarInset className="h-svh min-h-0 overflow-hidden">
          <Outlet />
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
