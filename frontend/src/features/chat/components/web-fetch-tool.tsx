import { Shimmer } from "@/shared/components/ai-elements/shimmer";
import { ToolOutput } from "@/shared/components/ai-elements/tool";
import { Badge } from "@/shared/components/ui/badge";

import { ToolPartShell } from "./tool-part-shell";
import type { ChatToolPart, WebFetchOutput } from "../types";
import { hostnameOf } from "../utils/citations";
import { readTitle } from "../utils/web-tools";

type WebFetchPart = Extract<ChatToolPart, { type: "tool-web_fetch" }>;

const EXCERPT_CHARS = 600;

/**
 * A `web_fetch` call. Our tool returns the page's text (an excerpt is shown); a model's built-in
 * fetch (`providerExecuted`) only reports which page it opened — no text, no number — so the
 * header reads "Read <host>" and the body is the link alone.
 */
export function WebFetchTool({ part }: { part: WebFetchPart }) {
  const url = part.input?.url;
  const landedEmpty = part.state === "output-available" && part.output.content.length === 0;
  const title = url
    ? landedEmpty
      ? readTitle(url)
      : `Fetched ${hostnameOf(url)}`
    : "Fetching a page";

  return (
    <ToolPartShell part={part} title={title}>
      {part.state === "input-available" && <Shimmer duration={1}>Reading the page…</Shimmer>}
      {part.state === "output-error" && (
        <ToolOutput output={undefined} errorText={part.errorText} />
      )}
      {part.state === "output-available" && <FetchResult output={part.output} />}
    </ToolPartShell>
  );
}

function FetchResult({ output }: { output: WebFetchOutput }) {
  const hasContent = output.content.length > 0;
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        {output.sourceId && <Badge variant="outline">{output.sourceId}</Badge>}
        <a
          href={output.url}
          target="_blank"
          rel="noreferrer"
          className="min-w-0 truncate font-medium underline-offset-4 hover:underline"
        >
          {output.title ?? output.url}
        </a>
        {hasContent && <Badge variant="secondary">{output.chars.toLocaleString()} chars</Badge>}
        {output.truncated && <Badge variant="secondary">truncated</Badge>}
      </div>
      {hasContent && (
        <p className="whitespace-pre-wrap text-muted-foreground">
          {output.content.slice(0, EXCERPT_CHARS)}
          {output.content.length > EXCERPT_CHARS ? "…" : ""}
        </p>
      )}
    </div>
  );
}
