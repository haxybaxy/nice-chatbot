import type { SourceUrlUIPart } from "ai";

/** `[n]` that is not already the text of a markdown link (`[n](…)`). */
const CITATION = /\[(\d+)\](?!\()/g;
/** Fenced code blocks, kept verbatim: a `[1]` inside code is not a citation. */
const FENCE = /(```[\s\S]*?```)/;

/**
 * Turn the agent's `[n]` citations into markdown links to the matching `source-url` part, so
 * `MessageResponse` renders them as anchors that `CitationAnchor` recognises (href = the source
 * url). Numbers without a source are left as written.
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

const TRACKING_PREFIX = "utm_";

/**
 * The URL without its `utm_*` parameters, the form the backend stores a cited page in. A model's
 * inline citation may still carry `?utm_source=chatgpt.com`; comparing both sides through this
 * matches the link in the text to its `source-url` part. The result is normalised by `URL` (and
 * the remaining query re-serialised) so two spellings of one address compare equal; a string
 * `URL` cannot parse is returned as is.
 */
export function stripTracking(url: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return url;
  }
  const kept = [...parsed.searchParams].filter(([key]) => !key.startsWith(TRACKING_PREFIX));
  parsed.search = new URLSearchParams(kept).toString();
  return parsed.toString();
}

export function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
