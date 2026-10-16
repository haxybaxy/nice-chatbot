import type { ChatStatus } from "ai";
import { useState } from "react";
import { toast } from "sonner";

import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputHeader,
  PromptInputTextarea,
  PromptInputTools,
} from "@/shared/components/ai-elements/prompt-input";
import { cn } from "@/shared/utils";

import { AttachFilesButton } from "./attach-files-button";
import { ComposerAttachments } from "./composer-attachments";
import { ComposerModeButtons } from "./composer-mode-buttons";
import { ComposerSubmitButton } from "./composer-submit-button";
import {
  type PendingAttachment,
  useComposerAttachments,
  useComposerFileEvents,
} from "../hooks/use-composer-attachments";
import { useComposerFocus } from "../hooks/use-composer-focus";
import { type ComposerSettings, resolveModel } from "../hooks/use-composer-settings";
import { usePendingUploads } from "../hooks/use-pending-uploads";
import type { ChatModel, ComposerSubmission } from "../types";
import { ATTACHMENT_MAX_FILES, isImageMediaType } from "../utils/attachments";

interface ChatComposerProps {
  /** Uploads are per team (`POST /api/teams/{team_id}/attachments`). */
  teamId: string;
  status: ChatStatus;
  /**
   * Called once every pending file is uploaded. Resolve when the message was accepted — the
   * thread does so at once (the optimistic message is in), a new chat once it is created; a
   * rejection keeps the text and the files for a retry.
   */
  onSubmit: (message: ComposerSubmission) => void | Promise<void>;
  onStop: () => void;
  settings: ComposerSettings;
  onSettingsChange: (patch: Partial<ComposerSettings>) => void;
  models: readonly ChatModel[];
}

/**
 * ChatGPT's pill around the vendored `InputGroup` (`PromptInput` renders it as the form's only
 * child): the radius, the surface, a soft shadow in light mode and no focus ring. Styled from
 * the outside so `prompt-input.tsx` / `input-group.tsx` stay as shipped — a child selector
 * (`.form > [data-slot=input-group]`) out-specifies the group's own utilities, and adding the
 * group's `:has(…:focus-visible)` condition out-specifies its focus ring too.
 */
const COMPOSER_SHELL = cn(
  "[&>[data-slot=input-group]]:rounded-[28px] [&>[data-slot=input-group]]:border-border [&>[data-slot=input-group]]:bg-background [&>[data-slot=input-group]]:shadow-[0_2px_12px_rgba(0,0,0,0.06)]",
  "dark:[&>[data-slot=input-group]]:border-transparent dark:[&>[data-slot=input-group]]:bg-card dark:[&>[data-slot=input-group]]:shadow-none",
  "[&>[data-slot=input-group]:has([data-slot=input-group-control]:focus-visible)]:border-border [&>[data-slot=input-group]:has([data-slot=input-group-control]:focus-visible)]:ring-0",
  "dark:[&>[data-slot=input-group]:has([data-slot=input-group-control]:focus-visible)]:border-transparent"
);

const reportRejectedFile = (message: string) => toast.error(message);

/** An image is attached but the model cannot see: the attachment strip says so. */
function needsVisionHint(model: ChatModel | undefined, files: readonly PendingAttachment[]) {
  return (
    model?.supportsVision === false && files.some((entry) => isImageMediaType(entry.file.type))
  );
}

/**
 * The prompt box, laid out like ChatGPT's: the textarea on top; under it the `+` for files,
 * the Search / Code / Deep research pills and, on the right, the round send button that turns
 * into Stop while a response runs. Submitting needs a `ready` thread, no upload in flight and
 * some text or at least one file; the files are uploaded first (`usePendingUploads`), then
 * `onSubmit` gets the text and the uploads as SDK file parts. The textarea keeps the focus
 * through a send or a stop (`useComposerFocus`).
 *
 * The pending files are the composer's own state (`useComposerAttachments`), not the vendored
 * `PromptInput`'s: its list hands `onSubmit` data/blob URLs, and a multipart upload needs the
 * `File`s. The vendored textarea still owns Enter-to-submit; paste, drop and Backspace are
 * `useComposerFileEvents`.
 */
export function ChatComposer({
  teamId,
  status,
  onSubmit,
  onStop,
  settings,
  onSettingsChange,
  models,
}: ChatComposerProps) {
  const [text, setText] = useState("");
  const { textareaRef, focus } = useComposerFocus();
  const attachments = useComposerAttachments(reportRejectedFile);
  const { uploadAll, isUploading } = usePendingUploads(teamId);
  const fileEvents = useComposerFileEvents(attachments, isUploading);

  const hasContent = text.trim().length > 0 || attachments.files.length > 0;
  const canSubmit = status === "ready" && !isUploading && hasContent;
  const model = resolveModel(settings, models);
  const showVisionHint = needsVisionHint(model, attachments.files);

  const submit = async () => {
    if (!canSubmit) {
      return;
    }
    const files = await uploadAll(attachments.files);
    await onSubmit({ text: text.trim(), files });
    setText("");
    attachments.clear();
    focus();
  };

  const stop = () => {
    onStop();
    focus();
  };

  return (
    <PromptInput
      className={COMPOSER_SHELL}
      onSubmit={submit}
      onDragOverCapture={fileEvents.onDragOverCapture}
      onDropCapture={fileEvents.onDropCapture}
    >
      {attachments.files.length > 0 && (
        <PromptInputHeader className="px-4 pt-3 pb-0">
          <ComposerAttachments
            files={attachments.files}
            onRemove={attachments.remove}
            uploading={isUploading}
            showVisionHint={showVisionHint}
          />
        </PromptInputHeader>
      )}
      <PromptInputBody>
        <PromptInputTextarea
          ref={textareaRef}
          aria-label="Message"
          placeholder="Ask anything"
          className="max-h-72 min-h-12 px-4 pt-3.5 pb-2 text-base leading-6 md:text-base"
          value={text}
          onChange={(event) => setText(event.currentTarget.value)}
          onPaste={fileEvents.onPaste}
          onKeyDown={fileEvents.onKeyDown}
        />
      </PromptInputBody>
      <PromptInputFooter className="px-3 pt-1 pb-3">
        <PromptInputTools className="gap-1.5">
          <AttachFilesButton
            disabled={isUploading || attachments.files.length >= ATTACHMENT_MAX_FILES}
            onFiles={attachments.add}
          />
          <ComposerModeButtons
            settings={settings}
            onSettingsChange={onSettingsChange}
            model={model}
          />
        </PromptInputTools>
        <ComposerSubmitButton status={status} canSubmit={canSubmit} onStop={stop} />
      </PromptInputFooter>
    </PromptInput>
  );
}
