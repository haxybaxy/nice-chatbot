import type { DynamicToolUIPart } from "ai";
import type { ReactNode } from "react";
import { useState } from "react";

import { Tool, ToolContent, ToolHeader } from "@/shared/components/ai-elements/tool";

import type { ChatToolPart } from "../types";

interface ToolPartShellProps {
  part: ChatToolPart | DynamicToolUIPart;
  /** The human sentence for the header ("Searched for …"); the tool name is the fallback. */
  title: string;
  children?: ReactNode;
  /**
   * Whether the body shows until the user toggles it. Collapsed by default — the result is a
   * detail, the answer is the message — but a tool may derive it from its state (the code tool
   * opens while it runs). The user's own toggle wins from then on.
   */
  open?: boolean;
}

/** The collapsible every tool part renders in: header with status badge, body with the tool's view. */
export function ToolPartShell({ part, title, children, open = false }: ToolPartShellProps) {
  const [toggled, setToggled] = useState<boolean | null>(null);

  return (
    <Tool
      open={toggled ?? open}
      onOpenChange={setToggled}
      data-tool={part.type}
      data-tool-state={part.state}
    >
      {part.type === "dynamic-tool" ? (
        <ToolHeader type="dynamic-tool" state={part.state} toolName={part.toolName} title={title} />
      ) : (
        <ToolHeader type={part.type} state={part.state} title={title} />
      )}
      <ToolContent>{children}</ToolContent>
    </Tool>
  );
}
