import type { SourceUrlUIPart } from "ai";

/** `[n]` that is not already the text of a markdown link (`[n](…)`). */
const CITATION = /\[(\d+)\](?!\()/g;
/** Fenced code blocks, kept verbatim: a `[1]` inside code is not a citation. */
const FENCE = /(```[\s\S]*?```)/;

/**
 * Turn the agent's `[n]` citations into markdown links to the matching `source-url` part, so
 * `MessageResponse` renders them as anchors that `CitationAnchor` recognises (href = the source
 * url, text = `[n]`). Numbers without a source are left as written.
 */
export function linkCitations(text: string, sources: readonly SourceUrlUIPart[]): string {
  if (sources.length === 0) {
    return text;
  }
  const urlById = new Map(sources.map((source) => [source.sourceId, source.url]));
  return text
    .split(FENCE)
    .map((segment, index) =>
      index % 2 === 1
        ? segment
        : segment.replace(CITATION, (match, id: string) => {
            const url = urlById.get(id);
            return url ? `[${match}](${url})` : match;
          })
    )
    .join("");
}

/** The citation label an anchor must carry to count as one. */
export const CITATION_LABEL = /^\[\d+\]$/;

export function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
