import { Shimmer } from "@/shared/components/ai-elements/shimmer";
import { ToolOutput } from "@/shared/components/ai-elements/tool";
import { Badge } from "@/shared/components/ui/badge";

import { ToolPartShell } from "./tool-part-shell";
import type { ChatToolPart, WebSearchResult } from "../types";
import { hostnameOf } from "../utils/citations";
import { searchedForTitle } from "../utils/web-tools";

type WebSearchPart = Extract<ChatToolPart, { type: "tool-web_search" }>;

/**
 * A `web_search` call. The Tavily tool returns numbered, titled hits with snippets; a model's
 * built-in search (`providerExecuted`) returns the pages it consulted, url only, and cites them
 * through the message's `source-url` parts — so a hit may have nothing but a hostname to show.
 */
export function WebSearchTool({ part }: { part: WebSearchPart }) {
  const query = part.input?.query;
  const title = query ? searchedForTitle(query) : "Searching the web";

  return (
    <ToolPartShell part={part} title={title}>
      {part.providerExecuted && <p className="text-xs text-muted-foreground">Built-in search</p>}
      {part.state === "input-available" && <Shimmer duration={1}>Searching…</Shimmer>}
      {part.state === "output-error" && (
        <ToolOutput output={undefined} errorText={part.errorText} />
      )}
      {part.state === "output-available" && <SearchResults results={part.output.results} />}
    </ToolPartShell>
  );
}

function SearchResults({ results }: { results: readonly WebSearchResult[] }) {
  if (results.length === 0) {
    return <p className="text-sm text-muted-foreground">No results.</p>;
  }
  return (
    <ol className="space-y-3 text-sm">
      {results.map((result, index) => (
        <li key={`${result.url}#${index}`} className="flex gap-2">
          {result.sourceId && (
            <Badge variant="outline" className="mt-0.5 shrink-0">
              {result.sourceId}
            </Badge>
          )}
          <SearchHit result={result} />
        </li>
      ))}
    </ol>
  );
}

/** Title (the hostname when there is none), then hostname · date — only what the hit has. */
function SearchHit({ result }: { result: WebSearchResult }) {
  const hostname = hostnameOf(result.url);
  const meta = [result.title ? hostname : null, result.publishedAt]
    .filter((entry) => Boolean(entry))
    .join(" · ");
  return (
    <div className="min-w-0">
      <a
        href={result.url}
        target="_blank"
        rel="noreferrer"
        className="font-medium underline-offset-4 hover:underline"
      >
        {result.title ?? hostname}
      </a>
      {meta && <p className="truncate text-xs text-muted-foreground">{meta}</p>}
      {result.snippet && <p className="text-muted-foreground">{result.snippet}</p>}
    </div>
  );
}
