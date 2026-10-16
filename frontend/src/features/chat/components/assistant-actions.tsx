import { CheckIcon, CopyIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { MessageAction, MessageActions } from "@/shared/components/ai-elements/message";
import { cn } from "@/shared/utils";

const COPIED_FOR_MS = 2000;

interface AssistantActionsProps {
  /** What Copy puts on the clipboard: the answer's text, as markdown. */
  text: string;
  /** Always visible under the last answer; earlier ones show theirs on hover or focus. */
  isLast: boolean;
}

/** The row under a finished answer — Copy, for now — in ChatGPT's quiet icon style. */
export function AssistantActions({ text, isLast }: AssistantActionsProps) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) {
      return undefined;
    }
    const timer = window.setTimeout(() => setCopied(false), COPIED_FOR_MS);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
  };

  return (
    <MessageActions
      className={cn(
        "-ml-1.5",
        !isLast && "opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
      )}
      data-testid="assistant-actions"
    >
      <MessageAction
        tooltip={copied ? "Copied" : "Copy"}
        label="Copy"
        className="text-muted-foreground hover:text-foreground"
        onClick={() => void copy()}
      >
        {copied ? <CheckIcon /> : <CopyIcon />}
      </MessageAction>
    </MessageActions>
  );
}
