import { FileCodeIcon, FileTextIcon, ImageIcon, type LucideIcon } from "lucide-react";

import { isImageMediaType } from "./attachments";

const PROSE_TYPES = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "text/markdown",
  "text/csv",
  "text/tab-separated-values",
]);
const PROSE_EXTENSIONS = new Set([".txt", ".md", ".markdown", ".csv", ".tsv", ".pdf", ".docx"]);

/** The icon of an attachment chip: image, prose document, or code/data for everything else. */
export function attachmentIcon(mediaType: string, filename: string): LucideIcon {
  if (isImageMediaType(mediaType)) {
    return ImageIcon;
  }
  const extension = filename.slice(filename.lastIndexOf(".")).toLowerCase();
  if (PROSE_TYPES.has(mediaType.toLowerCase()) || PROSE_EXTENSIONS.has(extension)) {
    return FileTextIcon;
  }
  return FileCodeIcon;
}
