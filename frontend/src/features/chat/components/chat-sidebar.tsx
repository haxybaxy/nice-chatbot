import { SquarePenIcon } from "lucide-react";
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
import { NEW_CHAT_SHORTCUT, useNewChatShortcut } from "../hooks/use-new-chat-shortcut";

/** The chat shell's sidebar, laid out like ChatGPT's: team switcher, "New chat", the team's conversations by day, the account menu. */
export function ChatSidebar({ team }: { team: Team }) {
  useNewChatShortcut(team.id);
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
                  <Link to={ROUTES.app.teamChat(team.id)} title={`New chat (${NEW_CHAT_SHORTCUT})`}>
                    <SquarePenIcon />
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
