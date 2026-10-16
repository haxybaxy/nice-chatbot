/**
 * Chat types.
 *
 * Everything on the wire is an alias of the generated schemas (`Schema<"…">`). The AI SDK side
 * (`ChatMessage`) is `UIMessage` specialised with the tool and data-part payloads the backend
 * emits; those payloads are `unknown` in the OpenAPI document (`ToolPartOut.input/output`,
 * `DataPartOut.data`), so they are the one place a type is written by hand — each anchored to
 * its wire slot with `Narrows<>` and turned into a typed part by the runtime guards in
 * `../utils/payload-guards.ts`, never by a cast.
 */
import type { DataUIPart, FileUIPart, ToolUIPart, UIMessage } from "ai";

import type { Narrows, Schema } from "@/shared/api/types";

// ── Wire aliases ─────────────────────────────────────────────────────────────

/** One entry of the model picker (`ModelOut`). */
export type ChatModel = Schema<"ModelOut">;

/** A conversation row (`ConversationOut`); `activeRun` is set while a response is being produced. */
export type Conversation = Schema<"ConversationOut">;

/** `GET /api/teams/{team_id}/conversations` page (`ConversationPageOut`). */
export type ConversationPage = Schema<"ConversationPageOut">;

/** `GET /api/conversations/{conversation_id}`: the row plus its persisted messages. */
export type ConversationDetail = Schema<"ConversationDetailOut">;

/** `POST /api/teams/{team_id}/conversations` body (optionally with the first message). */
export type CreateConversationRequest = Schema<"CreateConversationIn">;

/** `PATCH /api/conversations/{conversation_id}` body. */
export type UpdateConversationRequest = Schema<"UpdateConversationIn">;

/** `POST /api/conversations/{conversation_id}/messages` body. */
export type CreateMessageRequest = Schema<"CreateMessageIn">;

/** One entry of `CreateMessageIn.parts`: a text part or a reference to an uploaded attachment. */
export type MessagePartRequest = CreateMessageRequest["parts"][number];

/** An uploaded file (`AttachmentOut`): what `POST /api/teams/{team_id}/attachments` returns. */
export type Attachment = Schema<"AttachmentOut">;

/** The run settings a message is sent with: what the composer decides (`CreateMessageIn` minus `parts`). */
export type RunRequestOptions = Pick<CreateMessageRequest, "model" | "mode" | "tools">;

export type RunMode = Schema<"RunMode">;

/** A run (`RunOut`): one assistant response being produced, queued or finished. */
export type Run = Schema<"RunOut">;

/** A persisted message (`MessageOut`). */
export type WireMessage = Schema<"MessageOut">;

/** A persisted message part — the discriminated union the backend folds a run's events into. */
export type WirePart = Schema<"MessagePartOut">;

export type WireTextPart = Extract<WirePart, { type: "text" }>;
export type WireReasoningPart = Extract<WirePart, { type: "reasoning" }>;
export type WireSourceUrlPart = Extract<WirePart, { type: "source-url" }>;
export type WireStepStartPart = Extract<WirePart, { type: "step-start" }>;
/** `tool-<name>` parts; `type` is a plain string on the wire (the pattern is `^tool-`). */
export type WireToolPart = Extract<WirePart, { toolCallId: string }>;
/** `data-<name>` parts; `type` is a plain string on the wire (the pattern is `^data-`). */
export type WireDataPart = Extract<WirePart, { data: unknown }>;

// ── Tool payloads (hand-written: `unknown` on the wire) ─────────────────────
//
// Inputs are the model's arguments as it emitted them (the backend forwards `call.args`
// untouched), so only the fields the UI renders are named; outputs are the backend's
// `*Out` schemas dumped by alias (camelCase).

/** `web_search`'s arguments; a built-in search joins several queries with ` | `. */
export type WebSearchInput = Narrows<WireToolPart["input"], { query: string }>;
/**
 * One hit. The Tavily tool fills every field and numbers the hit (`sourceId`); a built-in
 * search (`providerExecuted`) only knows the pages it consulted — `url` alone, `title: null`,
 * `snippet: ""` — and cites through `source-url` parts instead.
 */
export interface WebSearchResult {
  url: string;
  title?: string | null;
  snippet?: string;
  sourceId?: string | null;
  publishedAt?: string | null;
  score?: number | null;
}
export type WebSearchOutput = Narrows<
  WireToolPart["output"],
  { query: string; results: WebSearchResult[] }
>;

/** `web_fetch`'s arguments (`{ url, query }` for a built-in find-in-page). */
export type WebFetchInput = Narrows<WireToolPart["input"], { url: string }>;
/** The page; a built-in fetch reports it with `sourceId: null`, no title and empty content. */
export type WebFetchOutput = Narrows<
  WireToolPart["output"],
  {
    sourceId?: string | null;
    url: string;
    title?: string | null;
    content: string;
    chars: number;
    truncated: boolean;
  }
>;

type CodeLanguage = "python" | "bash";
export type CodeInput = Narrows<WireToolPart["input"], { language: CodeLanguage; code: string }>;
export type CodeOutput = Narrows<
  WireToolPart["output"],
  {
    stdout: string;
    stderr: string;
    exitCode: number;
    durationMs: number;
    truncated: boolean;
    timedOut: boolean;
  }
>;

/** The tools the agent can call, keyed by wire name (`tool-web_search`, …). */
export type ChatTools = {
  web_search: { input: WebSearchInput; output: WebSearchOutput };
  web_fetch: { input: WebFetchInput; output: WebFetchOutput };
  run_code: { input: CodeInput; output: CodeOutput };
};

// ── Data parts (hand-written: `unknown` on the wire) ────────────────────────

export type ResearchTaskStatus = "pending" | "running" | "done" | "failed" | "skipped";

interface ResearchPlanTask {
  id: string;
  title: string;
  objective: string;
  status: ResearchTaskStatus;
}

/** `data-research-plan` (id `plan`): the plan of a deep-research run, replaced in place. */
export type ResearchPlan = Narrows<
  WireDataPart["data"],
  { summary: string; complexity: string; tasks: ResearchPlanTask[] }
>;

/** `data-research-task` (id = task id): one task's progress, replaced in place as it advances. */
export type ResearchTask = Narrows<
  WireDataPart["data"],
  {
    id: string;
    title: string;
    status: ResearchTaskStatus;
    toolCalls: number;
    lastAction?: string | null;
    summary?: string | null;
  }
>;

/** `data-research-citations` (id `citations`): what the citation check could not verify. */
export type ResearchCitations = Narrows<
  WireDataPart["data"],
  { unsupported: string[]; unknownNumbers: number[] }
>;

/** `data-refusal`: the model declined; rendered as a notice. */
export type Refusal = Narrows<
  WireDataPart["data"],
  { category?: string | null; explanation?: string | null }
>;

/** `data-conversation-title` (transient): the generated title, applied to the caches in `onData`. */
type ConversationTitle = Narrows<WireDataPart["data"], { title: string }>;

/** `data-tool-progress` (transient): a tool's heartbeat; not rendered. */
type ToolProgress = Narrows<WireDataPart["data"], { toolCallId: string; status: string }>;

export type ChatDataParts = {
  "research-plan": ResearchPlan;
  "research-task": ResearchTask;
  "research-citations": ResearchCitations;
  refusal: Refusal;
  "conversation-title": ConversationTitle;
  "tool-progress": ToolProgress;
};

// ── The UI message ───────────────────────────────────────────────────────────

/** Provenance copied from the persisted message; the stream sends no message metadata. */
type ChatMessageMetadata = Pick<WireMessage, "createdAt" | "model" | "provider" | "runId">;

/** The thread's message type: what `useChat` holds and what `toChatMessage` builds from a `MessageOut`. */
export type ChatMessage = UIMessage<ChatMessageMetadata, ChatDataParts, ChatTools>;

export type ChatMessagePart = ChatMessage["parts"][number];
export type ChatToolPart = ToolUIPart<ChatTools>;
export type ChatDataPart = DataUIPart<ChatDataParts>;

/**
 * What the composer hands over on submit — a client-only shape, never on the wire: the trimmed
 * text and the uploads already converted to SDK file parts (`toFileUIPart`), which `useChat`
 * appends as the optimistic user message and the transport maps back to `FilePartIn`.
 */
export interface ComposerSubmission {
  text: string;
  files: FileUIPart[];
}
