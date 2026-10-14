import { DownloadIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/shared/components/ui/button";
import { Spinner } from "@/shared/components/ui/spinner";

import { useDownloadAttachment } from "../../hooks/use-attachments";

/** Save the attachment under its filename (`useDownloadAttachment`); failures are toasted. */
export function DownloadAttachmentButton({
  attachmentId,
  filename,
  labelled = false,
}: {
  attachmentId: string;
  filename: string;
  /** Show the label next to the icon (the dialog footer) instead of icon-only (a chip). */
  labelled?: boolean;
}) {
  const download = useDownloadAttachment();
  const label = `Download ${filename}`;
  return (
    <Button
      type="button"
      variant={labelled ? "outline" : "ghost"}
      size={labelled ? "sm" : "icon-xs"}
      aria-label={label}
      title={label}
      disabled={download.isPending}
      onClick={() =>
        download.mutate(
          { attachmentId, filename },
          { onError: (error) => toast.error(`Could not download ${filename}: ${error.message}`) }
        )
      }
    >
      {download.isPending ? <Spinner /> : <DownloadIcon />}
      {labelled && "Download"}
    </Button>
  );
}
