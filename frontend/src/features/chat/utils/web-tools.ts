/**
 * The human sentences of the web tools, shared by their parts' headers (`web-search-tool.tsx`,
 * `web-fetch-tool.tsx`) and the activity line under a streaming answer (`assistant-activity.tsx`).
 */
import { hostnameOf } from "./citations";

/** A built-in search can run several queries in one call; the backend joins them with ` | `. */
const QUERY_SEPARATOR = " | ";

/** `"a | b"` → `"a · b"`; a single query is shown as written. */
function formatSearchQuery(query: string): string {
  return query
    .split(QUERY_SEPARATOR)
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
    .join(" · ");
}

export function searchedForTitle(query: string): string {
  return `Searched for “${formatSearchQuery(query)}”`;
}

/** `Read <host>`: a built-in fetch reports which page it opened, not its text. */
export function readTitle(url: string): string {
  return `Read ${hostnameOf(url)}`;
}
