import { PaperclipIcon } from "lucide-react";
import { useRef } from "react";

import { PromptInputButton } from "@/shared/components/ai-elements/prompt-input";

import { ATTACHMENT_ACCEPT } from "../utils/attachments";

interface AttachFilesButtonProps {
  disabled: boolean;
  onFiles: (files: Iterable<File>) => void;
}

/** The paperclip and the hidden picker behind it (`accept` = every allowed type and extension). */
export function AttachFilesButton({ disabled, onFiles }: AttachFilesButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ATTACHMENT_ACCEPT}
        className="hidden"
        aria-label="Files to attach"
        onChange={(event) => {
          onFiles(event.currentTarget.files ?? []);
          // So the same file can be picked again after it was removed.
          event.currentTarget.value = "";
        }}
      />
      <PromptInputButton
        type="button"
        aria-label="Attach files"
        title="Attach files"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        <PaperclipIcon />
      </PromptInputButton>
    </>
  );
}
