import type { SourceUrlUIPart } from "ai";
import { GlobeIcon } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/shared/components/ui/badge";

import { hostnameOf } from "../utils/citations";

/**
 * The pages an answer cites, as a wrapped row of chips under it — favicon, `[n]`, hostname —
 * one per `source-url` part, in the order the backend numbered them. The `[n]` matches the
 * citation pills in the text (`CitationAnchor`, fed by the same `CitationSourcesContext`).
 *
 * Privacy trade-off: the favicons come from Google's `s2/favicons` service, so every hostname an
 * answer cites is disclosed to Google by the reader's browser (with no referrer and no cookies
 * beyond what the browser sends to that origin). If that matters, swap `faviconUrl` for
 * DuckDuckGo's `https://icons.duckduckgo.com/ip3/<host>.ico` or a backend proxy; the chip falls
 * back to a globe icon whichever service fails.
 */
export function SourceChips({ sources }: { sources: readonly SourceUrlUIPart[] }) {
  if (sources.length === 0) {
    return null;
  }
  return (
    <div className="not-prose mt-3 space-y-2 text-xs" data-testid="source-chips">
      <p className="font-medium text-muted-foreground">{`Sources · ${sources.length}`}</p>
      <ul className="flex flex-wrap gap-2">
        {sources.map((source) => (
          <li key={source.sourceId}>
            <SourceChip source={source} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function SourceChip({ source }: { source: SourceUrlUIPart }) {
  const hostname = hostnameOf(source.url);
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noreferrer"
      title={source.title ?? source.url}
      className="inline-flex h-7 max-w-full items-center gap-1.5 rounded-full border border-border bg-background px-2.5 text-foreground no-underline transition-colors hover:bg-muted"
    >
      <Favicon hostname={hostname} />
      <Badge variant="outline" className="h-4 px-1 text-[10px]">
        {`[${source.sourceId}]`}
      </Badge>
      <span className="truncate">{hostname}</span>
    </a>
  );
}

const faviconUrl = (hostname: string) =>
  `https://www.google.com/s2/favicons?domain=${encodeURIComponent(hostname)}&sz=32`;

/** The site's favicon, or a globe once the request failed (offline, blocked, no icon). */
function Favicon({ hostname }: { hostname: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return <GlobeIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />;
  }
  return (
    <img
      src={faviconUrl(hostname)}
      alt=""
      width={16}
      height={16}
      loading="lazy"
      referrerPolicy="no-referrer"
      className="size-4 shrink-0 rounded-sm"
      onError={() => setFailed(true)}
    />
  );
}
