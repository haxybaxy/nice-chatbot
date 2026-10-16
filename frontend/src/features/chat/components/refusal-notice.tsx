import { ShieldAlertIcon } from "lucide-react";

import type { Refusal } from "../types";

/** `data-refusal`: the model declined. A muted notice, not an error. */
export function RefusalNotice({ refusal }: { refusal: Refusal }) {
  return (
    <div
      role="note"
      className="not-prose mb-2 flex gap-2 rounded-xl border bg-muted/40 p-3 text-sm text-muted-foreground"
    >
      <ShieldAlertIcon className="mt-0.5 size-4 shrink-0" />
      <div>
        <p className="font-medium text-foreground">
          The assistant declined to answer{refusal.category ? ` (${refusal.category})` : ""}.
        </p>
        {refusal.explanation && <p>{refusal.explanation}</p>}
      </div>
    </div>
  );
}
