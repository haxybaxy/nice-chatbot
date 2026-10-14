/**
 * The render plan of an assistant message: its parts in order, with consecutive reasoning
 * merged into one block, `source-url` parts collected for the sources list and the citation
 * anchors, and the deep-research data parts folded into one panel state (`data-research-task`
 * reconciled by task id, newest state wins). `step-start` and transient channels are skipped.
 */
import type { DynamicToolUIPart, SourceUrlUIPart } from "ai";
import { isToolUIPart } from "ai";

import type {
  ChatMessagePart,
  ChatToolPart,
  Refusal,
  ResearchCitations,
  ResearchPlan,
  ResearchTask,
} from "../types";

export type AssistantBlock =
  | { kind: "reasoning"; key: string; text: string; streaming: boolean }
  | { kind: "text"; key: string; text: string; streaming: boolean }
  | { kind: "tool"; key: string; part: ChatToolPart }
  | { kind: "dynamic-tool"; key: string; part: DynamicToolUIPart }
  | { kind: "refusal"; key: string; data: Refusal };

export interface ResearchState {
  plan: ResearchPlan | null;
  /** In order of first appearance; each entry is the task's latest state. */
  tasks: ResearchTask[];
  citations: ResearchCitations | null;
}

export interface AssistantContent {
  blocks: AssistantBlock[];
  sources: SourceUrlUIPart[];
  research: ResearchState | null;
}

export function toAssistantContent(parts: readonly ChatMessagePart[]): AssistantContent {
  const blocks: AssistantBlock[] = [];
  const sources: SourceUrlUIPart[] = [];
  let research: ResearchState | null = null;
  const researchState = () => (research ??= { plan: null, tasks: [], citations: null });

  parts.forEach((part, index) => {
    const key = `${part.type}-${index}`;
    if (part.type === "reasoning") {
      const previous = blocks.at(-1);
      if (previous?.kind === "reasoning") {
        previous.text += part.text;
        previous.streaming = part.state === "streaming";
      } else {
        blocks.push({
          kind: "reasoning",
          key,
          text: part.text,
          streaming: part.state === "streaming",
        });
      }
      return;
    }
    if (part.type === "text") {
      blocks.push({ kind: "text", key, text: part.text, streaming: part.state === "streaming" });
      return;
    }
    if (part.type === "source-url") {
      sources.push(part);
      return;
    }
    if (isToolUIPart(part)) {
      blocks.push(
        part.type === "dynamic-tool"
          ? { kind: "dynamic-tool", key: part.toolCallId, part }
          : { kind: "tool", key: part.toolCallId, part }
      );
      return;
    }
    switch (part.type) {
      case "data-research-plan":
        researchState().plan = part.data;
        return;
      case "data-research-task":
        upsertTask(researchState().tasks, part.data);
        return;
      case "data-research-citations":
        researchState().citations = part.data;
        return;
      case "data-refusal":
        blocks.push({ kind: "refusal", key, data: part.data });
        return;
      default:
        return;
    }
  });

  return { blocks, sources, research };
}

function upsertTask(tasks: ResearchTask[], task: ResearchTask): void {
  const index = tasks.findIndex((existing) => existing.id === task.id);
  if (index === -1) {
    tasks.push(task);
  } else {
    tasks[index] = task;
  }
}
