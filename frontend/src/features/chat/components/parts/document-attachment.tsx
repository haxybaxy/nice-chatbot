import type { FileUIPart } from "ai";
import { FileWarningIcon } from "lucide-react";

import { AttachmentChip } from "./attachment-chip";
import { DownloadAttachmentButton } from "./download-attachment-button";
import { useAttachment } from "../../hooks/use-attachments";
import { attachmentIcon } from "../../utils/attachment-icon";
import { describeAttachmentError, formatBytes } from "../../utils/attachments";

/**
 * A non-image attachment: a chip with its name, its size once the metadata is in, and a
 * download action. The metadata request doubles as the availability check (403/404 → muted).
 */
export function DocumentAttachment({
  attachmentId,
  part,
}: {
  attachmentId: string;
  part: FileUIPart;
}) {
  const meta = useAttachment(attachmentId);
  const name = part.filename ?? "file";

  if (meta.isError) {
    return (
      <AttachmentChip
        icon={FileWarningIcon}
        name={name}
        meta={describeAttachmentError(meta.error)}
        muted
      />
    );
  }
  return (
    <AttachmentChip
      icon={attachmentIcon(part.mediaType, name)}
      name={name}
      meta={meta.data ? formatBytes(meta.data.sizeBytes) : "…"}
      action={<DownloadAttachmentButton attachmentId={attachmentId} filename={name} />}
    />
  );
}
