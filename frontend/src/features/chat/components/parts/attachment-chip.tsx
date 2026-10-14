import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/shared/utils";

interface AttachmentChipProps {
  icon: LucideIcon;
  name: string;
  /** The second line: a size, a status ("Uploading…"), or why it cannot be shown. */
  meta?: ReactNode;
  /** A trailing control: remove in the composer, download in a message. */
  action?: ReactNode;
  /** Dimmed: the attachment is unavailable. */
  muted?: boolean;
  className?: string;
}

/** A non-image attachment, in the composer and in a user message alike. */
export function AttachmentChip({
  icon: Icon,
  name,
  meta,
  action,
  muted,
  className,
}: AttachmentChipProps) {
  return (
    <div
      className={cn(
        "flex h-12 max-w-64 items-center gap-2 rounded-md border bg-background px-2 text-xs",
        muted && "opacity-60",
        className
      )}
      title={name}
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{name}</div>
        {meta !== undefined && <div className="truncate text-muted-foreground">{meta}</div>}
      </div>
      {action}
    </div>
  );
}
