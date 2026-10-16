import type { DynamicToolUIPart } from "ai";
import type { ReactNode } from "react";
import { useState } from "react";

import { Tool, ToolContent } from "@/shared/components/ai-elements/tool";
import { CollapsibleTrigger } from "@/shared/components/ui/collapsible";

import { DisclosureLabel } from "./disclosure-label";
import type { ChatToolPart } from "../types";

interface ToolPartShellProps {
  part: ChatToolPart | DynamicToolUIPart;
  /** The human sentence for the line ("Searched for …"); the tool name is the fallback. */
  title: string;
  children?: ReactNode;
  /**
   * Whether the body shows until the user toggles it. Collapsed by default — the result is a
   * detail, the answer is the message — but a tool may derive it from its state (the code tool
   * opens while it runs). The user's own toggle wins from then on.
   */
  open?: boolean;
}

const isRunning = (state: ToolPartShellProps["part"]["state"]) =>
  state === "input-streaming" || state === "input-available";

/**
 * The collapsible every tool part renders in, the way ChatGPT shows its tool use: one muted line
 * — the sentence, shimmering while the tool runs — with a chevron, and the tool's view under it.
 * No card and no status badge: the sentence already says what happened.
 */
export function ToolPartShell({ part, title, children, open = false }: ToolPartShellProps) {
  const [toggled, setToggled] = useState<boolean | null>(null);
  const isOpen = toggled ?? open;

  return (
    <Tool
      open={isOpen}
      onOpenChange={setToggled}
      data-tool={part.type}
      data-tool-state={part.state}
      className="mb-2 rounded-none border-0"
    >
      <CollapsibleTrigger className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground">
        <DisclosureLabel text={title} busy={isRunning(part.state)} open={isOpen} />
      </CollapsibleTrigger>
      <ToolContent className="px-0 pt-2 pb-3">{children}</ToolContent>
    </Tool>
  );
}
