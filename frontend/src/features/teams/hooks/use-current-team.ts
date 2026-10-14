import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ROUTES } from "@/shared/constants/routes";
import { STORAGE_KEYS } from "@/shared/constants/storage-keys";
import { storage } from "@/shared/services/local-storage";

import { useMyTeams } from "./use-teams";
import { pickTeam } from "../utils/pick-team";

/**
 * The team of the current `/app/teams/:teamId/…` route, validated against the caller's teams.
 * Remembers a valid team as the one `/app` reopens, and redirects an unknown id (a stale
 * bookmark, a team the caller left) to the remembered or first team. Called by `ChatLayout`,
 * which renders nothing team-scoped until `team` is set.
 */
export function useCurrentTeam() {
  const { teamId } = useParams();
  const teams = useMyTeams();
  const navigate = useNavigate();
  const team = teams.data?.find((candidate) => candidate.id === teamId) ?? null;

  useEffect(() => {
    if (!teams.data) {
      return;
    }
    if (team) {
      storage.setString(STORAGE_KEYS.LAST_TEAM_ID, team.id);
      return;
    }
    const fallback = pickTeam(teams.data, storage.getString(STORAGE_KEYS.LAST_TEAM_ID));
    if (fallback) {
      navigate(ROUTES.app.teamChat(fallback.id), { replace: true });
    }
  }, [team, teams.data, navigate]);

  return { team, teams: teams.data ?? [], isPending: teams.isPending, error: teams.error };
}
