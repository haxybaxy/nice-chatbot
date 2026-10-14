import { Shimmer } from "@/shared/components/ai-elements/shimmer";
import { ToolOutput } from "@/shared/components/ai-elements/tool";
import { Badge } from "@/shared/components/ui/badge";

import { ToolPartShell } from "./tool-part-shell";
import type { ChatToolPart } from "../types";
import { hostnameOf } from "../utils/citations";

type WebSearchPart = Extract<ChatToolPart, { type: "tool-web_search" }>;

export function WebSearchTool({ part }: { part: WebSearchPart }) {
  const query = part.input?.query;
  const title = query ? `Searched for “${query}”` : "Searching the web";

  return (
    <ToolPartShell part={part} title={title}>
      {part.state === "input-available" && <Shimmer duration={1}>Searching…</Shimmer>}
      {part.state === "output-error" && (
        <ToolOutput output={undefined} errorText={part.errorText} />
      )}
      {part.state === "output-available" && (
        <ol className="space-y-3 text-sm">
          {part.output.results.map((result) => (
            <li key={result.sourceId} className="flex gap-2">
              <Badge variant="outline" className="mt-0.5 shrink-0">
                {result.sourceId}
              </Badge>
              <div className="min-w-0">
                <a
                  href={result.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium underline-offset-4 hover:underline"
                >
                  {result.title}
                </a>
                <p className="truncate text-xs text-muted-foreground">
                  {hostnameOf(result.url)}
                  {result.publishedAt ? ` · ${result.publishedAt}` : ""}
                </p>
                {result.snippet && <p className="text-muted-foreground">{result.snippet}</p>}
              </div>
            </li>
          ))}
          {part.output.results.length === 0 && (
            <li className="text-muted-foreground">No results.</li>
          )}
        </ol>
      )}
    </ToolPartShell>
  );
}
