import type { ChatStatus } from "ai";
import { ArrowUpIcon, SquareIcon } from "lucide-react";

import { PromptInputSubmit } from "@/shared/components/ai-elements/prompt-input";

interface ComposerSubmitButtonProps {
  status: ChatStatus;
  /** There is something to send and the thread can take it. */
  canSubmit: boolean;
  onStop: () => void;
}

/**
 * ChatGPT's round send button: an arrow that is disabled until there is something to send, or
 * the stop square while a response runs (`PromptInputSubmit` turns the click into `onStop`
 * then, and labels the button "Submit" / "Stop").
 */
export function ComposerSubmitButton({ status, canSubmit, onStop }: ComposerSubmitButtonProps) {
  const isGenerating = status === "submitted" || status === "streaming";
  return (
    <PromptInputSubmit
      status={status}
      onStop={onStop}
      disabled={!isGenerating && !canSubmit}
      className="size-9 shrink-0 rounded-full"
    >
      {isGenerating ? (
        <SquareIcon className="size-3 fill-current" />
      ) : (
        <ArrowUpIcon className="size-5" />
      )}
    </PromptInputSubmit>
  );
}
