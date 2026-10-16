import { MoreHorizontalIcon, PencilIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu";
import {
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/shared/components/ui/sidebar";
import { Spinner } from "@/shared/components/ui/spinner";
import { ROUTES } from "@/shared/constants/routes";

import { DeleteConversationDialog } from "./delete-conversation-dialog";
import { RenameConversationDialog } from "./rename-conversation-dialog";
import type { Conversation } from "../types";
import { conversationTitle } from "../utils/conversations";

type ItemDialog = "rename" | "delete" | null;

interface ConversationListItemProps {
  conversation: Conversation;
  isActive: boolean;
}

/**
 * One sidebar row, title only like ChatGPT's (a spinner in front while a response is being
 * produced), and its Rename / Delete menu on hover.
 */
export function ConversationListItem({ conversation, isActive }: ConversationListItemProps) {
  const [dialog, setDialog] = useState<ItemDialog>(null);
  const title = conversationTitle(conversation);
  const closeDialog = (open: boolean) => {
    if (!open) setDialog(null);
  };

  return (
    <SidebarMenuItem>
      <SidebarMenuButton asChild isActive={isActive} tooltip={title}>
        <Link to={ROUTES.app.conversation(conversation.teamId, conversation.id)}>
          {conversation.activeRun && <Spinner aria-label="Response in progress" />}
          <span className="truncate">{title}</span>
        </Link>
      </SidebarMenuButton>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <SidebarMenuAction showOnHover aria-label={`Actions for ${title}`}>
            <MoreHorizontalIcon />
          </SidebarMenuAction>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="start">
          <DropdownMenuItem onSelect={() => setDialog("rename")}>
            <PencilIcon />
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onSelect={() => setDialog("delete")}>
            <Trash2Icon />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <RenameConversationDialog
        conversation={conversation}
        open={dialog === "rename"}
        onOpenChange={closeDialog}
      />
      <DeleteConversationDialog
        conversation={conversation}
        isCurrent={isActive}
        open={dialog === "delete"}
        onOpenChange={closeDialog}
      />
    </SidebarMenuItem>
  );
}
