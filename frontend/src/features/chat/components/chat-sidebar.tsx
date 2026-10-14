import { MessageSquarePlusIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { type Team, TeamSwitcher } from "@/features/teams";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/shared/components/ui/sidebar";
import { ROUTES } from "@/shared/constants/routes";

import { ConversationList } from "./conversation-list";
import { SidebarUserMenu } from "./sidebar-user-menu";

/** The chat shell's sidebar: team switcher, "New chat", the team's conversations, the user footer. */
export function ChatSidebar({ team }: { team: Team }) {
  return (
    <Sidebar>
      <SidebarHeader>
        <TeamSwitcher currentTeam={team} />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild>
                  <Link to={ROUTES.app.teamChat(team.id)}>
                    <MessageSquarePlusIcon />
                    New chat
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <ConversationList teamId={team.id} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarUserMenu />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
