import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/shared/components/ui/alert-dialog";
import { ROUTES } from "@/shared/constants/routes";
import { ApiError } from "@/shared/services/api-error";

import { useDeleteConversation } from "../hooks/use-conversations";
import type { Conversation } from "../types";
import { conversationTitle } from "../utils/conversations";

interface DeleteConversationDialogProps {
  conversation: Conversation;
  /** The conversation is the one on screen: deleting it navigates to the team's new-chat page. */
  isCurrent: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function DeleteConversationDialog({
  conversation,
  isCurrent,
  open,
  onOpenChange,
}: DeleteConversationDialogProps) {
  const remove = useDeleteConversation();
  const navigate = useNavigate();

  const onConfirm = () =>
    remove.mutate(
      { conversationId: conversation.id, teamId: conversation.teamId },
      {
        onSuccess: () => {
          toast.success("Conversation deleted");
          if (isCurrent) {
            navigate(ROUTES.app.teamChat(conversation.teamId), { replace: true });
          }
        },
        onError: (error) => {
          toast.error(
            error instanceof ApiError && error.status === 409
              ? "Stop the response before deleting this conversation."
              : error.message
          );
        },
        onSettled: () => onOpenChange(false),
      }
    );

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete “{conversationTitle(conversation)}”?</AlertDialogTitle>
          <AlertDialogDescription>
            The conversation and its messages are removed for every member of the team. This cannot
            be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={onConfirm} disabled={remove.isPending}>
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
