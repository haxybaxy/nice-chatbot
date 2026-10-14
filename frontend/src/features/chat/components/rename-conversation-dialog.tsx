import { revalidateLogic, submitMutation, useAppForm } from "@/shared/components/form";
import { FormAlert } from "@/shared/components/form/form-alert";
import { Button } from "@/shared/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/shared/components/ui/dialog";

import { useRenameConversation } from "../hooks/use-conversations";
import {
  type RenameConversationFormData,
  renameConversationSchema,
} from "../schemas/conversation-form.schemas";
import type { Conversation } from "../types";

interface RenameConversationDialogProps {
  conversation: Conversation;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RenameConversationDialog({
  conversation,
  open,
  onOpenChange,
}: RenameConversationDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename conversation</DialogTitle>
          <DialogDescription>The title is what the sidebar shows for it.</DialogDescription>
        </DialogHeader>
        {/* Mounted with the dialog so the default value is the title at the time it opens. */}
        <RenameForm conversation={conversation} onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function RenameForm({ conversation, onDone }: { conversation: Conversation; onDone: () => void }) {
  const rename = useRenameConversation();
  const form = useAppForm({
    defaultValues: { title: conversation.title ?? "" },
    validationLogic: revalidateLogic(),
    validators: { onDynamic: renameConversationSchema },
    onSubmit: submitMutation(async ({ title }: RenameConversationFormData) => {
      await rename.mutateAsync({ conversationId: conversation.id, title });
      onDone();
    }),
  });

  return (
    <form.AppForm>
      <form.Root>
        <form.AppField name="title">
          {(field) => <field.TextField label="Title" autoComplete="off" autoFocus />}
        </form.AppField>
        <FormAlert error={rename.error} />
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <form.SubmitButton pendingLabel="Saving…">Save</form.SubmitButton>
        </DialogFooter>
      </form.Root>
    </form.AppForm>
  );
}
