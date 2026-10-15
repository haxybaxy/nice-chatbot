import type { ChatStatus } from "ai";
import { useState } from "react";
import { toast } from "sonner";

import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputHeader,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/shared/components/ai-elements/prompt-input";

import { AttachFilesButton } from "./attach-files-button";
import { ComposerAttachments } from "./composer-attachments";
import { ComposerModeButtons } from "./composer-mode-buttons";
import { ModelSelect } from "./model-select";
import {
  type PendingAttachment,
  useComposerAttachments,
  useComposerFileEvents,
} from "../hooks/use-composer-attachments";
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
  placeholder?: string;
}

const reportRejectedFile = (message: string) => toast.error(message);

/** An image is attached but the model cannot see: the attachment strip says so. */
function needsVisionHint(model: ChatModel | undefined, files: readonly PendingAttachment[]) {
  return (
    model?.supportsVision === false && files.some((entry) => isImageMediaType(entry.file.type))
  );
}

/**
 * The prompt box: textarea + attachments (paperclip, drop, paste), model select, Chat / Deep
 * research mode, the Search and Code toggles (Chat mode only) and a submit button that turns
 * into Stop while a response runs. Submitting needs a `ready` thread, no upload in flight and
 * some text or at least one file; the files are uploaded first (`usePendingUploads`), then
 * `onSubmit` gets the text and the uploads as SDK file parts.
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
  placeholder = "Message the assistant…",
}: ChatComposerProps) {
  const [text, setText] = useState("");
  const attachments = useComposerAttachments(reportRejectedFile);
  const { uploadAll, isUploading } = usePendingUploads(teamId);
  const fileEvents = useComposerFileEvents(attachments, isUploading);

  const isGenerating = status === "submitted" || status === "streaming";
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
  };

  return (
    <PromptInput
      onSubmit={submit}
      onDragOverCapture={fileEvents.onDragOverCapture}
      onDropCapture={fileEvents.onDropCapture}
    >
      {attachments.files.length > 0 && (
        <PromptInputHeader>
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
          aria-label="Message"
          placeholder={placeholder}
          value={text}
          onChange={(event) => setText(event.currentTarget.value)}
          onPaste={fileEvents.onPaste}
          onKeyDown={fileEvents.onKeyDown}
        />
      </PromptInputBody>
      <PromptInputFooter>
        <PromptInputTools>
          <AttachFilesButton
            disabled={isUploading || attachments.files.length >= ATTACHMENT_MAX_FILES}
            onFiles={attachments.add}
          />
          <ModelSelect
            models={models}
            value={model?.id ?? null}
            onChange={(id) => onSettingsChange({ model: id })}
          />
          <ComposerModeButtons
            settings={settings}
            onSettingsChange={onSettingsChange}
            model={model}
          />
        </PromptInputTools>
        <PromptInputSubmit
          status={status}
          onStop={onStop}
          disabled={isGenerating ? false : !canSubmit}
        />
      </PromptInputFooter>
    </PromptInput>
  );
}
