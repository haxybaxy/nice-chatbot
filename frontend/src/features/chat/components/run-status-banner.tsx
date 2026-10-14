import { Alert, AlertDescription } from "@/shared/components/ui/alert";
import { Spinner } from "@/shared/components/ui/spinner";

import type { Run } from "../types";

/** Shown on a thread that mounted while a response was already being produced, until it ends. */
export function RunStatusBanner({ run }: { run: Run }) {
  const phase = run.status === "queued" ? "is queued" : "is still being written";
  return (
    <Alert role="status" className="mx-auto w-full max-w-3xl">
      <Spinner />
      <AlertDescription>
        A response {phase} — picking up where it left off
        {run.attempt > 1 ? ` (attempt ${run.attempt})` : ""}.
      </AlertDescription>
    </Alert>
  );
}
