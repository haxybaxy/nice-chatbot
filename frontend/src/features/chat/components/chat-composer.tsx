import type { ChatStatus, FileUIPart } from "ai";
import { CodeIcon, GlobeIcon, MessageSquareIcon, PaperclipIcon, TelescopeIcon } from "lucide-react";
import { type ClipboardEvent, type DragEvent, type KeyboardEvent, useRef, useState } from "react";
import { toast } from "sonner";

import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputHeader,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/shared/components/ai-elements/prompt-input";

import { ComposerAttachments } from "./composer-attachments";
import { ModelSelect } from "./model-select";
import {
  type UploadOutcome,
  useDeleteAttachment,
  useUploadAttachments,
} from "../hooks/use-attachments";
import { useComposerAttachments } from "../hooks/use-composer-attachments";
import { type ComposerSettings, resolveModelId } from "../hooks/use-composer-settings";
import type { Attachment, ChatModel, ComposerSubmission, RunMode } from "../types";
import {
  ATTACHMENT_ACCEPT,
  ATTACHMENT_MAX_FILES,
  isImageMediaType,
  toFileUIPart,
} from "../utils/attachments";

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

const MODES: readonly { mode: RunMode; label: string; icon: typeof MessageSquareIcon }[] = [
  { mode: "chat", label: "Chat", icon: MessageSquareIcon },
  { mode: "deep_research", label: "Deep research", icon: TelescopeIcon },
];

const reportRejectedFile = (message: string) => toast.error(message);

const isUploaded = (
  outcome: UploadOutcome
): outcome is Extract<UploadOutcome, { attachment: Attachment }> =>
  outcome.attachment !== undefined;

function hasFiles(transfer: DataTransfer | null): boolean {
  return transfer !== null && Array.from(transfer.types).includes("Files");
}

function pastedFiles(transfer: DataTransfer | null): File[] {
  const files: File[] = [];
  for (const item of transfer?.items ?? []) {
    const file = item.kind === "file" ? item.getAsFile() : null;
    if (file) {
      files.push(file);
    }
  }
  return files;
}

/**
 * The prompt box: textarea + attachments (paperclip, drop, paste), model select, Chat / Deep
 * research mode, the Search and Code toggles (Chat mode only) and a submit button that turns
 * into Stop while a response runs. Submitting needs a `ready` thread, no upload in flight and
 * some text or at least one file; the files are uploaded first (one `AttachmentOut` each), then
 * `onSubmit` gets the text and the uploads as SDK file parts.
 *
 * The pending files are the composer's own state (`useComposerAttachments`), not the vendored
 * `PromptInput`'s: its list hands `onSubmit` data/blob URLs, and a multipart upload needs the
 * `File`s. The vendored textarea still owns Enter-to-submit; paste and drop are intercepted
 * here (the drop in the capture phase, ahead of the form's own listener).
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const attachments = useComposerAttachments(reportRejectedFile);
  const upload = useUploadAttachments(teamId);
  const discard = useDeleteAttachment();

  const isGenerating = status === "submitted" || status === "streaming";
  const isUploading = upload.isPending;
  const hasContent = text.trim().length > 0 || attachments.files.length > 0;
  const canSubmit = status === "ready" && !isUploading && hasContent;
  const model = models.find((entry) => entry.id === resolveModelId(settings, models));
  const showVisionHint =
    model?.supportsVision === false &&
    attachments.files.some((entry) => isImageMediaType(entry.file.type));

  /** Every pending file as an uploaded attachment, or a toast per failure and a rejection. */
  const uploadPending = async (): Promise<FileUIPart[]> => {
    if (attachments.files.length === 0) {
      return [];
    }
    const outcomes = await upload.mutateAsync(attachments.files.map((entry) => entry.file));
    const uploaded = outcomes.filter(isUploaded);
    if (uploaded.length === outcomes.length) {
      return uploaded.map((outcome) => toFileUIPart(outcome.attachment));
    }
    for (const outcome of outcomes) {
      if (outcome.error) {
        toast.error(`${outcome.file.name}: ${outcome.error.message}`);
      } else {
        // Best effort: the retry re-uploads everything; the reaper would sweep these anyway.
        discard.mutate(outcome.attachment.id);
      }
    }
    throw new Error("Some files could not be uploaded.");
  };

  const submit = async () => {
    if (!canSubmit) {
      return;
    }
    const files = await uploadPending();
    await onSubmit({ text: text.trim(), files });
    setText("");
    attachments.clear();
  };

  const onDragOverCapture = (event: DragEvent<HTMLFormElement>) => {
    if (hasFiles(event.dataTransfer)) {
      event.preventDefault();
      event.stopPropagation();
    }
  };
  const onDropCapture = (event: DragEvent<HTMLFormElement>) => {
    if (!hasFiles(event.dataTransfer)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    attachments.add(event.dataTransfer.files);
  };
  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = pastedFiles(event.clipboardData);
    if (files.length > 0) {
      event.preventDefault();
      attachments.add(files);
    }
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const last = attachments.files.at(-1);
    if (event.key === "Backspace" && event.currentTarget.value === "" && last && !isUploading) {
      event.preventDefault();
      attachments.remove(last.id);
    }
  };

  return (
    <PromptInput
      onSubmit={submit}
      onDragOverCapture={onDragOverCapture}
      onDropCapture={onDropCapture}
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
          onPaste={onPaste}
          onKeyDown={onKeyDown}
        />
      </PromptInputBody>
      <PromptInputFooter>
        <PromptInputTools>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ATTACHMENT_ACCEPT}
            className="hidden"
            aria-label="Files to attach"
            onChange={(event) => {
              if (event.currentTarget.files) {
                attachments.add(event.currentTarget.files);
              }
              // So the same file can be picked again after it was removed.
              event.currentTarget.value = "";
            }}
          />
          <PromptInputButton
            type="button"
            aria-label="Attach files"
            title="Attach files"
            disabled={isUploading || attachments.files.length >= ATTACHMENT_MAX_FILES}
            onClick={() => fileInputRef.current?.click()}
          >
            <PaperclipIcon />
          </PromptInputButton>
          <ModelSelect
            models={models}
            value={resolveModelId(settings, models)}
            onChange={(model) => onSettingsChange({ model })}
          />
          <div role="group" aria-label="Mode" className="flex items-center">
            {MODES.map(({ mode, label, icon: Icon }) => (
              <PromptInputButton
                key={mode}
                type="button"
                aria-pressed={settings.mode === mode}
                variant={settings.mode === mode ? "secondary" : "ghost"}
                onClick={() => onSettingsChange({ mode })}
              >
                <Icon />
                {label}
              </PromptInputButton>
            ))}
          </div>
          {settings.mode === "chat" && (
            <>
              <PromptInputButton
                type="button"
                aria-pressed={settings.webSearch}
                variant={settings.webSearch ? "secondary" : "ghost"}
                onClick={() => onSettingsChange({ webSearch: !settings.webSearch })}
              >
                <GlobeIcon />
                Search
              </PromptInputButton>
              <PromptInputButton
                type="button"
                aria-pressed={settings.code}
                variant={settings.code ? "secondary" : "ghost"}
                onClick={() => onSettingsChange({ code: !settings.code })}
              >
                <CodeIcon />
                Code
              </PromptInputButton>
            </>
          )}
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
