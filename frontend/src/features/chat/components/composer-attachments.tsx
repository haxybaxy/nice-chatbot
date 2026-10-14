import { XIcon } from "lucide-react";

import { Button } from "@/shared/components/ui/button";

import { AttachmentChip } from "./parts/attachment-chip";
import type { PendingAttachment } from "../hooks/use-composer-attachments";
import { attachmentIcon } from "../utils/attachment-icon";
import { formatBytes } from "../utils/attachments";

interface ComposerAttachmentsProps {
  files: readonly PendingAttachment[];
  onRemove: (id: string) => void;
  /** The files are being uploaded: no removing, and the chips say so. */
  uploading: boolean;
  /** The chosen model cannot see images, yet one is attached. */
  showVisionHint: boolean;
}

/** The strip above the textarea: one thumbnail or chip per pending file, with its remove button. */
export function ComposerAttachments({
  files,
  onRemove,
  uploading,
  showVisionHint,
}: ComposerAttachmentsProps) {
  if (files.length === 0) {
    return null;
  }
  return (
    <div className="flex w-full flex-col gap-2" data-testid="composer-attachments">
      <ul className="flex flex-wrap gap-2" aria-label="Attachments">
        {files.map(({ id, file, previewUrl }) => {
          const remove = (
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={`Remove ${file.name}`}
              disabled={uploading}
              onClick={() => onRemove(id)}
            >
              <XIcon />
            </Button>
          );
          return (
            <li key={id} className="relative">
              {previewUrl ? (
                <div className="flex h-12 items-center gap-2 rounded-md border bg-background pr-1 pl-1">
                  <img
                    src={previewUrl}
                    alt={file.name}
                    className="size-10 rounded-sm object-cover"
                    title={file.name}
                  />
                  {remove}
                </div>
              ) : (
                <AttachmentChip
                  icon={attachmentIcon(file.type, file.name)}
                  name={file.name}
                  meta={uploading ? "Uploading…" : formatBytes(file.size)}
                  action={remove}
                />
              )}
            </li>
          );
        })}
      </ul>
      {uploading && (
        <p role="status" className="text-xs text-muted-foreground">
          Uploading {files.length === 1 ? "1 file" : `${files.length} files`}…
        </p>
      )}
      {showVisionHint && (
        <p role="note" className="text-xs text-muted-foreground">
          This model can&apos;t view images; they will be described as attached.
        </p>
      )}
    </div>
  );
}
