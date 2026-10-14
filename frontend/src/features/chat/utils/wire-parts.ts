/**
 * `MessageOut` → `ChatMessage`: the persisted thread in the shape `useChat` holds.
 *
 * Plain object construction, no casts: the four structural parts map field by field; a
 * `tool-*` part becomes the typed tool part when its name is known and its payload passes the
 * guard (./payload-guards.ts), else a `dynamic-tool` part the generic shell can still render; a
 * `data-*` part becomes the typed data part or is dropped (nothing would render it). The
 * `start` chunk of a replayed run carries the persisted assistant message id, which is why a
 * resumed stream replaces the message `toChatMessage` built rather than adding a second one.
 */
import type { DynamicToolUIPart } from "ai";

import {
  isCodeInput,
  isCodeOutput,
  isRefusal,
  isResearchCitations,
  isResearchPlan,
  isResearchTask,
  isWebFetchInput,
  isWebFetchOutput,
  isWebSearchInput,
  isWebSearchOutput,
} from "./payload-guards";
import type {
  ChatDataPart,
  ChatMessage,
  ChatMessagePart,
  ChatToolPart,
  WireDataPart,
  WireMessage,
  WirePart,
  WireToolPart,
} from "../types";

/** The tool part types, pinned to the SDK's `tool-${name}` template over `ChatTools`. */
export const TOOL_PART_TYPES = {
  webSearch: "tool-web_search",
  webFetch: "tool-web_fetch",
  code: "tool-run_code",
} as const satisfies Record<string, ChatToolPart["type"]>;

export function toChatMessage(message: WireMessage): ChatMessage {
  return {
    id: message.id,
    role: message.role,
    metadata: {
      createdAt: message.createdAt,
      model: message.model,
      provider: message.provider,
      runId: message.runId,
    },
    parts: message.parts.flatMap(toUiPart),
  };
}

function toUiPart(part: WirePart): ChatMessagePart[] {
  if ("toolCallId" in part) {
    return [toKnownToolPart(part) ?? toDynamicToolPart(part)];
  }
  if ("data" in part) {
    const dataPart = toDataPart(part);
    return dataPart ? [dataPart] : [];
  }
  switch (part.type) {
    case "text":
      return [{ type: "text", text: part.text, ...partState(part.state) }];
    case "reasoning":
      return [{ type: "reasoning", text: part.text, ...partState(part.state) }];
    case "step-start":
      return [{ type: "step-start" }];
    case "source-url":
      return [
        {
          type: "source-url",
          sourceId: part.sourceId,
          url: part.url,
          ...(part.title ? { title: part.title } : {}),
        },
      ];
  }
}

/** The wire's `state?: PartState | null` as the SDK's optional `state`. */
function partState(state: "streaming" | "done" | null | undefined) {
  return state ? { state } : {};
}

// ── Tool parts ───────────────────────────────────────────────────────────────

type Invocation<I, O> =
  | { state: "input-available"; input: I }
  | { state: "output-available"; input: I; output: O }
  | { state: "output-error"; input: I | undefined; errorText: string };

/**
 * The state-dependent fields of a tool part, typed by the guards. `undefined` when the payload
 * is not what the tool's schema says — the caller falls back to a dynamic tool part.
 */
function toolInvocation<I, O>(
  part: WireToolPart,
  isInput: (value: unknown) => value is I,
  isOutput: (value: unknown) => value is O
): Invocation<I, O> | undefined {
  const { state, input, output, errorText } = part;
  if (state === "input-available") {
    return isInput(input) ? { state, input } : undefined;
  }
  if (state === "output-available") {
    return isInput(input) && isOutput(output) ? { state, input, output } : undefined;
  }
  return {
    state,
    input: isInput(input) ? input : undefined,
    errorText: errorText ?? "The tool failed",
  };
}

function toKnownToolPart(part: WireToolPart): ChatToolPart | undefined {
  const { toolCallId } = part;
  switch (part.type) {
    case TOOL_PART_TYPES.webSearch: {
      const invocation = toolInvocation(part, isWebSearchInput, isWebSearchOutput);
      return invocation && { type: TOOL_PART_TYPES.webSearch, toolCallId, ...invocation };
    }
    case TOOL_PART_TYPES.webFetch: {
      const invocation = toolInvocation(part, isWebFetchInput, isWebFetchOutput);
      return invocation && { type: TOOL_PART_TYPES.webFetch, toolCallId, ...invocation };
    }
    case TOOL_PART_TYPES.code: {
      const invocation = toolInvocation(part, isCodeInput, isCodeOutput);
      return invocation && { type: TOOL_PART_TYPES.code, toolCallId, ...invocation };
    }
    default:
      return undefined;
  }
}

/** A tool the UI has no renderer for (or a payload that failed its guard): shown generically. */
function toDynamicToolPart(part: WireToolPart): DynamicToolUIPart {
  const base = {
    type: "dynamic-tool",
    toolName: part.type.replace(/^tool-/, ""),
    toolCallId: part.toolCallId,
  } as const;
  switch (part.state) {
    case "input-available":
      return { ...base, state: "input-available", input: part.input };
    case "output-available":
      return { ...base, state: "output-available", input: part.input, output: part.output };
    case "output-error":
      return {
        ...base,
        state: "output-error",
        input: part.input,
        errorText: part.errorText ?? "The tool failed",
      };
  }
}

// ── Data parts ───────────────────────────────────────────────────────────────

function toDataPart(part: WireDataPart): ChatDataPart | undefined {
  const id = part.id ?? undefined;
  const { data } = part;
  switch (part.type) {
    case "data-research-plan":
      return isResearchPlan(data) ? { type: "data-research-plan", id, data } : undefined;
    case "data-research-task":
      return isResearchTask(data) ? { type: "data-research-task", id, data } : undefined;
    case "data-research-citations":
      return isResearchCitations(data) ? { type: "data-research-citations", id, data } : undefined;
    case "data-refusal":
      return isRefusal(data) ? { type: "data-refusal", id, data } : undefined;
    default:
      // Transient channels (`data-conversation-title`, `data-tool-progress`) are never persisted;
      // anything else is a part this UI does not know how to show.
      return undefined;
  }
}
