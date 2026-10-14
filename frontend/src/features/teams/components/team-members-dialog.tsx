import { XIcon } from "lucide-react";
import { toast } from "sonner";

import { revalidateLogic, submitMutation, useAppForm } from "@/shared/components/form";
import { FormAlert } from "@/shared/components/form/form-alert";
import { Button } from "@/shared/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/shared/components/ui/dialog";
import { Skeleton } from "@/shared/components/ui/skeleton";

import { useAddTeamMember, useRemoveTeamMember, useTeamMembers } from "../hooks/use-teams";
import { addTeamMemberSchema } from "../schemas/team-form.schemas";
import type { AddTeamMemberRequest, Team, TeamMember } from "../types";

interface TeamMembersDialogProps {
  team: Team;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Who is in the team, with add-by-email and remove. The list mounts (and fetches) with the dialog. */
export function TeamMembersDialog({ team, open, onOpenChange }: TeamMembersDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Members of {team.name}</DialogTitle>
          <DialogDescription>
            Members see every team conversation. Anyone with an account in the organization can be
            added by email.
          </DialogDescription>
        </DialogHeader>
        <MemberList teamId={team.id} />
        <AddMemberForm teamId={team.id} />
      </DialogContent>
    </Dialog>
  );
}

function MemberList({ teamId }: { teamId: string }) {
  const members = useTeamMembers(teamId);
  const remove = useRemoveTeamMember();

  if (members.isPending) {
    return (
      <div className="space-y-2" aria-busy="true">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }
  if (members.isError) {
    return <FormAlert error={members.error} />;
  }

  const onRemove = (member: TeamMember) =>
    remove.mutate(
      { teamId, userId: member.userId },
      {
        onError: (error) => toast.error(error.message),
      }
    );

  return (
    <ul className="divide-y rounded-md border text-sm">
      {members.data.map((member) => (
        <li key={member.userId} className="flex items-center gap-3 px-3 py-2">
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{member.user.fullName ?? member.user.email}</p>
            {member.user.fullName && (
              <p className="truncate text-xs text-muted-foreground">{member.user.email}</p>
            )}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={`Remove ${member.user.email}`}
            disabled={remove.isPending}
            onClick={() => onRemove(member)}
          >
            <XIcon />
          </Button>
        </li>
      ))}
    </ul>
  );
}

function AddMemberForm({ teamId }: { teamId: string }) {
  const addMember = useAddTeamMember();
  const form = useAppForm({
    defaultValues: { email: "" },
    validationLogic: revalidateLogic(),
    validators: { onDynamic: addTeamMemberSchema },
    onSubmit: submitMutation(async ({ email }: AddTeamMemberRequest) => {
      await addMember.mutateAsync({ teamId, email });
      form.reset();
    }),
  });

  return (
    <form.AppForm>
      <form.Root>
        <form.AppField name="email">
          {(field) => <field.TextField label="Add a member by email" type="email" />}
        </form.AppField>
        <FormAlert error={addMember.error} />
        <form.SubmitButton pendingLabel="Adding…">Add member</form.SubmitButton>
      </form.Root>
    </form.AppForm>
  );
}
