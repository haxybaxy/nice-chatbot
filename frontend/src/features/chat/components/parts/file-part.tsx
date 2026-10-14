import type { FileUIPart } from "ai";
import { FileWarningIcon } from "lucide-react";

import { AttachmentChip } from "./attachment-chip";
import { DocumentAttachment } from "./document-attachment";
import { ImageAttachment } from "./image-attachment";
import { attachmentIdFromUrl, isImageMediaType } from "../../utils/attachments";

/**
 * A `file` part of a user message — the optimistic one `useChat` appended and the persisted one
 * render through the same component: an image thumbnail or a document chip, both fetched
 * through the attachment id their `url` carries (never used as a raw `src`).
 */
export function FilePart({ part }: { part: FileUIPart }) {
  const attachmentId = attachmentIdFromUrl(part.url);
  if (!attachmentId) {
    return (
      <AttachmentChip
        icon={FileWarningIcon}
        name={part.filename ?? "file"}
        meta="Unavailable"
        muted
      />
    );
  }
  return isImageMediaType(part.mediaType) ? (
    <ImageAttachment attachmentId={attachmentId} part={part} />
  ) : (
    <DocumentAttachment attachmentId={attachmentId} part={part} />
  );
}
