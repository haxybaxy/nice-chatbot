import type { DynamicToolUIPart } from "ai";
import { isToolUIPart } from "ai";

import { Shimmer } from "@/shared/components/ai-elements/shimmer";

import type { ChatMessagePart, ChatToolPart } from "../types";
import { hostnameOf } from "../utils/citations";
import { readTitle, searchedForTitle } from "../utils/web-tools";
import { TOOL_PART_TYPES } from "../utils/wire-parts";

type AnyToolPart = ChatToolPart | DynamicToolUIPart;

/** The parts of the message's last step: everything after the last `step-start`. */
function lastStep(parts: readonly ChatMessagePart[]): readonly ChatMessagePart[] {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    if (parts[index]?.type === "step-start") {
      return parts.slice(index + 1);
    }
  }
  return parts;
}

/** The last element matching, searching from the end (`Array.prototype.findLast` is ES2023). */
function findLast<T>(items: readonly T[], matches: (item: T) => boolean): T | undefined {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item !== undefined && matches(item)) {
      return item;
    }
  }
  return undefined;
}

const isRunning = (part: AnyToolPart) =>
  part.state === "input-streaming" || part.state === "input-available";

const isWebTool = (part: AnyToolPart) =>
  part.type === TOOL_PART_TYPES.webSearch || part.type === TOOL_PART_TYPES.webFetch;

/** What a tool still running is doing. */
function runningLabel(part: AnyToolPart): string {
  switch (part.type) {
    case TOOL_PART_TYPES.webSearch:
      return "Searching the web…";
    case TOOL_PART_TYPES.webFetch: {
      const url = part.input?.url;
      return url ? `Reading ${hostnameOf(url)}…` : "Reading a page…";
    }
    case TOOL_PART_TYPES.code:
      return "Running code…";
    default:
      return "Working…";
  }
}

/** What a finished web tool did, while the answer that uses it has not started. */
function landedLabel(part: AnyToolPart): string {
  if (part.type === TOOL_PART_TYPES.webSearch) {
    const query = part.input?.query;
    return query ? searchedForTitle(query) : "Searched the web";
  }
  if (part.type === TOOL_PART_TYPES.webFetch) {
    const url = part.input?.url;
    return url ? readTitle(url) : "Read a page";
  }
  return "Working…";
}

/**
 * The one line describing what the assistant is doing right now, from the parts of its last
 * step: a running tool, else — until the step's text starts — the web tool that just finished,
 * else streaming reasoning, else just "Working…". Nothing once the step has text.
 */
function activityText(parts: readonly ChatMessagePart[]): string | null {
  const step = lastStep(parts);
  const tools = step.filter(isToolUIPart);
  const running = findLast(tools, isRunning);
  if (running) {
    return runningLabel(running);
  }
  if (step.some((part) => part.type === "text")) {
    return null;
  }
  const landed = findLast(tools, isWebTool);
  if (landed) {
    return landedLabel(landed);
  }
  if (step.some((part) => part.type === "reasoning" && part.state === "streaming")) {
    return "Thinking…";
  }
  return "Working…";
}

/**
 * The activity line under a streaming assistant message. Rendered only while the response
 * streams (`AssistantMessage` gates it); the thread's own "Thinking…" covers the gap before the
 * first chunk.
 */
export function AssistantActivity({ parts }: { parts: readonly ChatMessagePart[] }) {
  const text = activityText(parts);
  if (!text) {
    return null;
  }
  // `text-sm` only: the shimmer paints its gradient in `--color-muted-foreground` through
  // `bg-clip-text` + `text-transparent`, which a `text-*` colour class would override.
  return (
    <div data-testid="assistant-activity">
      <Shimmer duration={1} className="text-sm">
        {text}
      </Shimmer>
    </div>
  );
}
