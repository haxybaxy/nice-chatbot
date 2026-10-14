import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

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
import { ROUTES } from "@/shared/constants/routes";

import { useCreateTeam } from "../hooks/use-teams";
import { createTeamSchema } from "../schemas/team-form.schemas";
import type { CreateTeamRequest } from "../types";

interface CreateTeamDialogProps {
  /** The organization the new team is created in (the current team's). */
  organizationId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Create a team and switch to it. The form mounts with the dialog so its defaults are fresh. */
export function CreateTeamDialog({ organizationId, open, onOpenChange }: CreateTeamDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New team</DialogTitle>
          <DialogDescription>
            A team has its own conversations; add members from the team menu afterwards.
          </DialogDescription>
        </DialogHeader>
        <CreateTeamForm organizationId={organizationId} onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function CreateTeamForm({
  organizationId,
  onDone,
}: {
  organizationId: string;
  onDone: () => void;
}) {
  const createTeam = useCreateTeam();
  const navigate = useNavigate();
  const form = useAppForm({
    defaultValues: { name: "" },
    validationLogic: revalidateLogic(),
    validators: { onDynamic: createTeamSchema },
    onSubmit: submitMutation(async ({ name }: CreateTeamRequest) => {
      const team = await createTeam.mutateAsync({ organizationId, name });
      toast.success(`Team “${team.name}” created`);
      onDone();
      navigate(ROUTES.app.teamChat(team.id));
    }),
  });

  return (
    <form.AppForm>
      <form.Root>
        <form.AppField name="name">
          {(field) => <field.TextField label="Team name" autoComplete="off" autoFocus />}
        </form.AppField>
        <FormAlert error={createTeam.error} />
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <form.SubmitButton pendingLabel="Creating…">Create team</form.SubmitButton>
        </DialogFooter>
      </form.Root>
    </form.AppForm>
  );
}
