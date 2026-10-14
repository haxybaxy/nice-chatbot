/**
 * Attachment rules and conversions shared by the composer, the transport and the renderers.
 *
 * The limits and the accepted types mirror the backend's (`ATTACHMENT_MAX_BYTES`,
 * `ATTACHMENT_MAX_PER_MESSAGE`, its media-type and extension allowlists): the client checks
 * them to fail fast on a drop or a paste, the backend remains the authority (its 400 is shown
 * as is). A `file` part's `url` is `/api/attachments/{id}/content`, bearer-protected — the
 * SPA never uses it as a `src`; `attachmentIdFromUrl` recovers the id so the transport can send
 * `FilePartIn` and the renderers can fetch the bytes through `apiClient.blob`.
 */
import type { FileUIPart } from "ai";

import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { ApiError } from "@/shared/services/api-error";

import type { Attachment } from "../types";

export const ATTACHMENT_MAX_FILES = 5;
export const ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024;

const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
const DOCUMENT_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];
const TEXT_TYPES = [
  "application/json",
  "application/xml",
  "application/yaml",
  "application/x-yaml",
  "application/toml",
  "application/javascript",
  "application/x-javascript",
  "application/typescript",
  "application/x-sh",
  "application/sql",
];
/** Code and text files the OS often hands over with an empty or odd media type. */
const TEXT_EXTENSIONS = [
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".tsv",
  ".json",
  ".jsonl",
  ".xml",
  ".yaml",
  ".yml",
  ".toml",
  ".ini",
  ".cfg",
  ".env",
  ".log",
  ".sql",
  ".sh",
  ".bash",
  ".zsh",
  ".py",
  ".ts",
  ".tsx",
  ".js",
  ".jsx",
  ".mjs",
  ".cjs",
  ".go",
  ".rs",
  ".java",
  ".kt",
  ".swift",
  ".rb",
  ".php",
  ".c",
  ".h",
  ".cpp",
  ".hpp",
  ".cs",
  ".html",
  ".css",
  ".scss",
  ".svg",
  ".tex",
  ".r",
  ".scala",
  ".lua",
  ".dart",
  ".proto",
  ".graphql",
  ".dockerfile",
  ".gitignore",
];

/** The `accept` attribute of the file picker: every allowed media type and extension. */
export const ATTACHMENT_ACCEPT = [
  ...IMAGE_TYPES,
  ...DOCUMENT_TYPES,
  "text/*",
  ...TEXT_TYPES,
  ...TEXT_EXTENSIONS,
].join(",");

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot === -1 ? "" : filename.slice(dot).toLowerCase();
}

/** Whether the backend would accept this file's type (size and count are checked separately). */
export function isAcceptedFile(file: File): boolean {
  const type = file.type.toLowerCase();
  if (type.startsWith("text/")) return true;
  if (IMAGE_TYPES.includes(type) || DOCUMENT_TYPES.includes(type) || TEXT_TYPES.includes(type)) {
    return true;
  }
  return TEXT_EXTENSIONS.includes(extensionOf(file.name));
}

export function isImageMediaType(mediaType: string): boolean {
  return mediaType.startsWith("image/");
}

/** The content path with its one segment as a capture group, built from the spec path. */
const CONTENT_URL = new RegExp(
  `${API_ENDPOINTS.ATTACHMENTS.CONTENT.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(
    /\\\{attachment_id\\\}/,
    "([^/?#]+)"
  )}(?:[?#]|$)`
);

/** The attachment id inside a `file` part's `url` (relative or absolute), or `undefined`. */
export function attachmentIdFromUrl(url: string): string | undefined {
  const match = CONTENT_URL.exec(url);
  const id = match?.[1];
  if (!id) {
    return undefined;
  }
  try {
    return decodeURIComponent(id);
  } catch {
    return undefined;
  }
}

/**
 * An upload as the SDK file part the thread holds — the same four fields the backend persists
 * (`FilePartOut` minus `attachmentId`, which travels inside `url`), so the optimistic user
 * message renders exactly like the persisted one.
 */
export function toFileUIPart(attachment: Attachment): FileUIPart {
  return {
    type: "file",
    mediaType: attachment.mediaType,
    filename: attachment.filename,
    url: attachment.url,
  };
}

const UNITS = ["B", "KB", "MB", "GB"];

/** `1536` → `1.5 KB`; whole numbers below 10 keep one decimal. */
export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = unit === 0 ? Math.round(value) : Number(value.toFixed(value < 10 ? 1 : 0));
  return `${rounded} ${UNITS[unit]}`;
}

/**
 * Save an object URL under `filename` through a transient anchor — how a bearer-protected
 * download works without a navigable URL. The caller owns the URL's lifetime.
 */
export function downloadObjectUrl(url: string, filename: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}

/**
 * What a chip says when an attachment cannot be fetched: gone or not visible to this member
 * (403 / 404) is simply "Unavailable"; anything else names the failure.
 */
export function describeAttachmentError(error: Error): string {
  if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
    return "Unavailable";
  }
  return error.message;
}
