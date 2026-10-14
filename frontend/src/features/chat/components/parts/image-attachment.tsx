import type { FileUIPart } from "ai";
import { ImageOffIcon } from "lucide-react";
import { useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/shared/components/ui/dialog";
import { Skeleton } from "@/shared/components/ui/skeleton";

import { AttachmentChip } from "./attachment-chip";
import { DownloadAttachmentButton } from "./download-attachment-button";
import { useAttachmentObjectUrl } from "../../hooks/use-attachments";
import { describeAttachmentError } from "../../utils/attachments";

/** An image the user attached: a thumbnail from its object URL; click for the full size. */
export function ImageAttachment({
  attachmentId,
  part,
}: {
  attachmentId: string;
  part: FileUIPart;
}) {
  const objectUrl = useAttachmentObjectUrl(attachmentId);
  const [open, setOpen] = useState(false);
  const name = part.filename ?? "image";

  if (objectUrl.isPending) {
    return <Skeleton className="h-32 w-40 rounded-md" aria-label={`Loading ${name}`} />;
  }
  if (objectUrl.isError) {
    return (
      <AttachmentChip
        icon={ImageOffIcon}
        name={name}
        meta={describeAttachmentError(objectUrl.error)}
        muted
      />
    );
  }
  return (
    <>
      <button
        type="button"
        className="block overflow-hidden rounded-md border bg-background"
        aria-label={`Open ${name}`}
        onClick={() => setOpen(true)}
      >
        <img src={objectUrl.data} alt={name} className="max-h-48 max-w-full object-contain" />
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="truncate">{name}</DialogTitle>
            <DialogDescription className="sr-only">Full-size preview of {name}</DialogDescription>
          </DialogHeader>
          <img src={objectUrl.data} alt={name} className="max-h-[75vh] w-full object-contain" />
          <DialogFooter>
            <DownloadAttachmentButton attachmentId={attachmentId} filename={name} labelled />
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
