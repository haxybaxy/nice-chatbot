import type { FileUIPart } from "ai";
import { useCallback } from "react";
import { toast } from "sonner";

import { type UploadOutcome, useDeleteAttachment, useUploadAttachments } from "./use-attachments";
import type { PendingAttachment } from "./use-composer-attachments";
import type { Attachment } from "../types";
import { toFileUIPart } from "../utils/attachments";

const isUploaded = (
  outcome: UploadOutcome
): outcome is Extract<UploadOutcome, { attachment: Attachment }> =>
  outcome.attachment !== undefined;

/**
 * The composer's upload step: every pending file to the team, in parallel, as the SDK file
 * parts the message will carry. All or nothing — when any file is refused, each failure is
 * toasted, the uploads that did succeed are withdrawn (best effort; the retry re-uploads
 * everything and the reaper would sweep them anyway) and the promise rejects, so the composer
 * keeps its text and files.
 */
export function usePendingUploads(teamId: string) {
  const upload = useUploadAttachments(teamId);
  const discard = useDeleteAttachment();
  const { mutateAsync: uploadFiles } = upload;
  const { mutate: discardAttachment } = discard;

  const uploadAll = useCallback(
    async (pending: readonly PendingAttachment[]): Promise<FileUIPart[]> => {
      if (pending.length === 0) {
        return [];
      }
      const outcomes = await uploadFiles(pending.map((entry) => entry.file));
      if (outcomes.every(isUploaded)) {
        return outcomes.map((outcome) => toFileUIPart(outcome.attachment));
      }
      for (const outcome of outcomes) {
        if (outcome.error) {
          toast.error(`${outcome.file.name}: ${outcome.error.message}`);
        } else {
          discardAttachment(outcome.attachment.id);
        }
      }
      throw new Error("Some files could not be uploaded.");
    },
    [uploadFiles, discardAttachment]
  );

  return { uploadAll, isUploading: upload.isPending };
}
