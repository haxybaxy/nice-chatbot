/**
 * UI message parts → `CreateMessageIn.parts`: the one place the outgoing shape is built, used by
 * the transport (`sendMessages`) and by the new-conversation screen (`CreateConversationIn.message`).
 *
 * A text part stays a `TextPartIn`; a `file` part becomes `FilePartIn{type, attachmentId}` with
 * the id read from its `url` (`/api/attachments/{id}/content`) — nothing else, because the
 * request schema is `extra="forbid"` (no `mediaType`, `filename` or `url` on the wire). The
 * backend requires at least one non-empty text part or one file part; sending less is a
 * programming error here, so it throws instead of letting the server 400.
 */
import { isFileUIPart, isTextUIPart } from "ai";

import { attachmentIdFromUrl } from "./attachments";
import type { ChatMessagePart, MessagePartRequest } from "../types";

export function toMessagePartsIn(parts: readonly ChatMessagePart[]): MessagePartRequest[] {
  const out: MessagePartRequest[] = [];
  let hasContent = false;
  for (const part of parts) {
    if (isTextUIPart(part)) {
      out.push({ type: "text", text: part.text });
      hasContent ||= part.text.trim().length > 0;
    } else if (isFileUIPart(part)) {
      const attachmentId = attachmentIdFromUrl(part.url);
      if (!attachmentId) {
        throw new Error(`"${part.filename ?? part.url}" is not an uploaded attachment.`);
      }
      out.push({ type: "file", attachmentId });
      hasContent = true;
    }
  }
  if (!hasContent) {
    throw new Error("The message has no text and no attachment.");
  }
  return out;
}
