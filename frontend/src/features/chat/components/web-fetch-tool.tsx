import { Shimmer } from "@/shared/components/ai-elements/shimmer";
import { ToolOutput } from "@/shared/components/ai-elements/tool";
import { Badge } from "@/shared/components/ui/badge";

import { ToolPartShell } from "./tool-part-shell";
import type { ChatToolPart } from "../types";
import { hostnameOf } from "../utils/citations";

type WebFetchPart = Extract<ChatToolPart, { type: "tool-web_fetch" }>;

const EXCERPT_CHARS = 600;

export function WebFetchTool({ part }: { part: WebFetchPart }) {
  const url = part.input?.url;
  const title = url ? `Fetched ${hostnameOf(url)}` : "Fetching a page";

  return (
    <ToolPartShell part={part} title={title}>
      {part.state === "input-available" && <Shimmer duration={1}>Reading the page…</Shimmer>}
      {part.state === "output-error" && (
        <ToolOutput output={undefined} errorText={part.errorText} />
      )}
      {part.state === "output-available" && (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{part.output.sourceId}</Badge>
            <a
              href={part.output.url}
              target="_blank"
              rel="noreferrer"
              className="min-w-0 truncate font-medium underline-offset-4 hover:underline"
            >
              {part.output.title ?? part.output.url}
            </a>
            <Badge variant="secondary">{part.output.chars.toLocaleString()} chars</Badge>
            {part.output.truncated && <Badge variant="secondary">truncated</Badge>}
          </div>
          <p className="whitespace-pre-wrap text-muted-foreground">
            {part.output.content.slice(0, EXCERPT_CHARS)}
            {part.output.content.length > EXCERPT_CHARS ? "…" : ""}
          </p>
        </div>
      )}
    </ToolPartShell>
  );
}
