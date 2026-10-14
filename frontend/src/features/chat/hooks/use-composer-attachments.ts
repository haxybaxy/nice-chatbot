import { nanoid } from "nanoid";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ATTACHMENT_MAX_BYTES,
  ATTACHMENT_MAX_FILES,
  formatBytes,
  isAcceptedFile,
  isImageMediaType,
} from "../utils/attachments";

/** A file picked, dropped or pasted into the composer, not uploaded yet. */
export interface PendingAttachment {
  id: string;
  file: File;
  /** An object URL of the file itself for the image thumbnail; revoked when the entry goes. */
  previewUrl: string | null;
}

/**
 * The composer's pending files — client state, like the composer settings. The vendored
 * `PromptInput` keeps its own attachment list, but it hands `onSubmit` data/blob URLs rather
 * than the `File`s a multipart upload needs (reading them back would take `fetch`, which only
 * the two transports may call), so the composer owns the list and feeds it from its own
 * picker, the textarea's paste and the form's drop. Type, size and count are checked here
 * against the backend's limits; each refusal is reported through `onReject` (toasted), the
 * rest is kept.
 */
export function useComposerAttachments(onReject: (message: string) => void) {
  const [files, setFiles] = useState<PendingAttachment[]>([]);

  const add = useCallback(
    (incoming: Iterable<File>) => {
      const accepted: PendingAttachment[] = [];
      const problems: string[] = [];
      let room = ATTACHMENT_MAX_FILES - files.length;
      for (const file of incoming) {
        if (!isAcceptedFile(file)) {
          problems.push(`${file.name}: this file type is not supported.`);
        } else if (file.size > ATTACHMENT_MAX_BYTES) {
          problems.push(`${file.name}: larger than ${formatBytes(ATTACHMENT_MAX_BYTES)}.`);
        } else if (room <= 0) {
          problems.push(`At most ${ATTACHMENT_MAX_FILES} files per message.`);
          break;
        } else {
          room -= 1;
          accepted.push({
            id: nanoid(),
            file,
            previewUrl: isImageMediaType(file.type) ? URL.createObjectURL(file) : null,
          });
        }
      }
      if (accepted.length > 0) {
        setFiles((previous) => [...previous, ...accepted]);
      }
      for (const problem of problems) {
        onReject(problem);
      }
    },
    [files.length, onReject]
  );

  const remove = useCallback((id: string) => {
    setFiles((previous) => {
      const found = previous.find((entry) => entry.id === id);
      if (found?.previewUrl) {
        URL.revokeObjectURL(found.previewUrl);
      }
      return previous.filter((entry) => entry.id !== id);
    });
  }, []);

  const clear = useCallback(() => {
    setFiles((previous) => {
      for (const entry of previous) {
        if (entry.previewUrl) {
          URL.revokeObjectURL(entry.previewUrl);
        }
      }
      return [];
    });
  }, []);

  // The previews of whatever is still pending when the composer unmounts.
  const filesRef = useRef(files);
  useEffect(() => {
    filesRef.current = files;
  }, [files]);
  useEffect(
    () => () => {
      for (const entry of filesRef.current) {
        if (entry.previewUrl) {
          URL.revokeObjectURL(entry.previewUrl);
        }
      }
    },
    []
  );

  return { files, add, remove, clear };
}
