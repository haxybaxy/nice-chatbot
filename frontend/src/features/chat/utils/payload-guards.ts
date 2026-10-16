/**
 * Runtime guards for the payloads the OpenAPI document types as `unknown` (`ToolPartOut.input`
 * / `.output`, `DataPartOut.data`). `toChatMessage` (./wire-parts.ts) narrows a persisted part
 * through these instead of casting, so a payload the backend never produced cannot become a
 * typed part: it degrades to a generic tool part (or is dropped, for an unknown `data-*`). Named
 * structural probes — the sanctioned kind of hand-written shape (CLAUDE.md → Generated API types).
 */
import type {
  CodeInput,
  CodeOutput,
  Refusal,
  ResearchCitations,
  ResearchPlan,
  ResearchTask,
  ResearchTaskStatus,
  WebFetchInput,
  WebFetchOutput,
  WebSearchInput,
  WebSearchOutput,
  WebSearchResult,
} from "../types";

type Probe = Record<string, unknown>;

function isRecord(value: unknown): value is Probe {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const hasString = (record: Probe, key: string) => typeof record[key] === "string";
const hasNumber = (record: Probe, key: string) => typeof record[key] === "number";
const hasBoolean = (record: Probe, key: string) => typeof record[key] === "boolean";
/** `key?: string` — absent or a string. */
const hasOptionalString = (record: Probe, key: string) =>
  record[key] === undefined || hasString(record, key);
/** `key?: string | null` — absent, `null` or a string. */
const hasNullableString = (record: Probe, key: string) =>
  record[key] === null || hasOptionalString(record, key);

const TASK_STATUSES: readonly ResearchTaskStatus[] = [
  "pending",
  "running",
  "done",
  "failed",
  "skipped",
];
const isTaskStatus = (value: unknown): value is ResearchTaskStatus =>
  TASK_STATUSES.some((status) => status === value);

// ── Tools ────────────────────────────────────────────────────────────────────

export function isWebSearchInput(value: unknown): value is WebSearchInput {
  return isRecord(value) && hasString(value, "query");
}

/** Only `url` is certain: a built-in search reports the pages it consulted and nothing else. */
function isWebSearchResult(value: unknown): value is WebSearchResult {
  return (
    isRecord(value) &&
    hasString(value, "url") &&
    hasNullableString(value, "title") &&
    hasOptionalString(value, "snippet") &&
    hasNullableString(value, "sourceId")
  );
}

export function isWebSearchOutput(value: unknown): value is WebSearchOutput {
  return (
    isRecord(value) &&
    hasString(value, "query") &&
    Array.isArray(value["results"]) &&
    value["results"].every(isWebSearchResult)
  );
}

export function isWebFetchInput(value: unknown): value is WebFetchInput {
  return isRecord(value) && hasString(value, "url");
}

export function isWebFetchOutput(value: unknown): value is WebFetchOutput {
  return (
    isRecord(value) &&
    hasNullableString(value, "sourceId") &&
    hasString(value, "url") &&
    hasString(value, "content") &&
    hasNumber(value, "chars") &&
    hasBoolean(value, "truncated")
  );
}

export function isCodeInput(value: unknown): value is CodeInput {
  return (
    isRecord(value) &&
    (value["language"] === "python" || value["language"] === "bash") &&
    hasString(value, "code")
  );
}

export function isCodeOutput(value: unknown): value is CodeOutput {
  return (
    isRecord(value) &&
    hasString(value, "stdout") &&
    hasString(value, "stderr") &&
    hasNumber(value, "exitCode") &&
    hasNumber(value, "durationMs") &&
    hasBoolean(value, "truncated") &&
    hasBoolean(value, "timedOut")
  );
}

// ── Data parts ───────────────────────────────────────────────────────────────

function isPlanTask(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasString(value, "id") &&
    hasString(value, "title") &&
    hasString(value, "objective") &&
    isTaskStatus(value["status"])
  );
}

export function isResearchPlan(value: unknown): value is ResearchPlan {
  return (
    isRecord(value) &&
    hasString(value, "summary") &&
    hasString(value, "complexity") &&
    Array.isArray(value["tasks"]) &&
    value["tasks"].every(isPlanTask)
  );
}

export function isResearchTask(value: unknown): value is ResearchTask {
  return (
    isRecord(value) &&
    hasString(value, "id") &&
    hasString(value, "title") &&
    isTaskStatus(value["status"]) &&
    hasNumber(value, "toolCalls")
  );
}

export function isResearchCitations(value: unknown): value is ResearchCitations {
  return (
    isRecord(value) && Array.isArray(value["unsupported"]) && Array.isArray(value["unknownNumbers"])
  );
}

export function isRefusal(value: unknown): value is Refusal {
  return isRecord(value);
}
