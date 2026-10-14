import { Navigate } from "react-router-dom";

import { Loading } from "@/shared/components/feedback";
import { Alert, AlertDescription } from "@/shared/components/ui/alert";
import { Button } from "@/shared/components/ui/button";
import { ROUTES } from "@/shared/constants/routes";
import { STORAGE_KEYS } from "@/shared/constants/storage-keys";
import { storage } from "@/shared/services/local-storage";

import { useMyTeams } from "../hooks/use-teams";
import { pickTeam } from "../utils/pick-team";

/**
 * The `/app` index: sends the signed-in user to the chat of the team they last used (else their
 * first team). Sign-up always creates one team, so an empty list is a backend state worth
 * naming rather than a spinner forever.
 */
export function AppIndexRedirect() {
  const teams = useMyTeams();

  if (teams.isPending) {
    return <Loading fullHeight label="Loading your teams…" />;
  }
  if (teams.isError) {
    return (
      <div className="mx-auto max-w-md p-6">
        <Alert variant="destructive">
          <AlertDescription>
            Could not load your teams: {teams.error.message}
            <Button variant="outline" size="sm" onClick={() => void teams.refetch()}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const target = pickTeam(teams.data, storage.getString(STORAGE_KEYS.LAST_TEAM_ID));
  if (!target) {
    return (
      <div className="mx-auto max-w-md p-6 text-center text-sm text-muted-foreground">
        You are not a member of any team yet. Ask a team member to add you.
      </div>
    );
  }
  return <Navigate to={ROUTES.app.teamChat(target.id)} replace />;
}
