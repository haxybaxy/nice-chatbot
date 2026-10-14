import { useParams } from "react-router-dom";

import { Button } from "@/shared/components/ui/button";
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuSkeleton,
} from "@/shared/components/ui/sidebar";

import { ConversationListItem } from "./conversation-list-item";
import { useConversations } from "../hooks/use-conversations";
import { groupConversationsByDay } from "../utils/conversations";

/** The team's conversations grouped by day, with the active one highlighted and a "Load more". */
export function ConversationList({ teamId }: { teamId: string }) {
  const { conversationId } = useParams();
  const query = useConversations(teamId);

  if (query.isPending) {
    return (
      <SidebarGroup aria-busy="true">
        <SidebarGroupLabel>Conversations</SidebarGroupLabel>
        <SidebarMenu>
          {[0, 1, 2].map((index) => (
            <SidebarMenuItem key={index}>
              <SidebarMenuSkeleton />
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroup>
    );
  }
  if (query.isError) {
    return (
      <SidebarGroup>
        <SidebarGroupLabel>Conversations</SidebarGroupLabel>
        <p role="alert" className="px-2 text-xs text-destructive">
          Could not load conversations.
        </p>
        <Button variant="ghost" size="sm" onClick={() => void query.refetch()}>
          Try again
        </Button>
      </SidebarGroup>
    );
  }

  const conversations = query.data.pages.flatMap((page) => page.items);
  if (conversations.length === 0) {
    return (
      <SidebarGroup>
        <SidebarGroupLabel>Conversations</SidebarGroupLabel>
        <p className="px-2 text-xs text-muted-foreground">No conversations yet.</p>
      </SidebarGroup>
    );
  }

  return (
    <>
      {groupConversationsByDay(conversations).map((group) => (
        <SidebarGroup key={group.label}>
          <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {group.items.map((conversation) => (
                <ConversationListItem
                  key={conversation.id}
                  conversation={conversation}
                  isActive={conversation.id === conversationId}
                />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      ))}
      {query.hasNextPage && (
        <div className="px-2 pb-2">
          <Button
            variant="ghost"
            size="sm"
            className="w-full"
            onClick={() => void query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
          >
            {query.isFetchingNextPage ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </>
  );
}
