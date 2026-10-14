import type {
  Attachment,
  ChatModel,
  Conversation,
  ConversationDetail,
  Run,
  WireMessage,
  WirePart,
} from "@/features/chat/types";

let counter = 1;

const NOW = "2026-01-01T12:00:00Z";
export const DEFAULT_MODEL_ID = "anthropic:claude-opus-5-5";

/** One model-picker entry (`ModelOut`). */
export function makeModel(overrides: Partial<ChatModel> = {}): ChatModel {
  return {
    id: DEFAULT_MODEL_ID,
    provider: "anthropic",
    modelId: "claude-opus-5-5",
    displayName: "Claude Opus 5.5",
    tier: "frontier",
    supportsTools: true,
    supportsVision: true,
    supportsReasoning: true,
    isDefault: false,
    ...overrides,
  };
}

/** The resting catalog: the default frontier model and a balanced one. */
export const DEFAULT_MODELS: ChatModel[] = [
  makeModel({ isDefault: true }),
  makeModel({
    id: "anthropic:claude-sonnet-5-5",
    modelId: "claude-sonnet-5-5",
    displayName: "Claude Sonnet 5.5",
    tier: "balanced",
  }),
];

/** A run (`RunOut`): queued, chat mode, no tools, unless overridden. */
export function makeRun(overrides: Partial<Run> = {}): Run {
  const id = overrides.id ?? `run-${counter++}`;
  return {
    id,
    conversationId: "conv-1",
    status: "queued",
    mode: "chat",
    model: DEFAULT_MODEL_ID,
    provider: "anthropic",
    effort: "medium",
    options: { webSearch: false, code: false },
    attempt: 1,
    lastSeq: 0,
    createdAt: NOW,
    ...overrides,
  };
}

/** A conversation row (`ConversationOut`). Optional fields follow `exclude_none`: absent unless given. */
export function makeConversation(overrides: Partial<Conversation> = {}): Conversation {
  const id = overrides.id ?? `conv-${counter++}`;
  return {
    id,
    teamId: "team-1",
    visibility: "team",
    title: "Hello there",
    lastMessageAt: NOW,
    createdAt: NOW,
    updatedAt: NOW,
    createdBy: "user-1",
    ...overrides,
  };
}

/** A persisted `text` part, as the backend folds a finished text stream. */
export function textPart(text: string): WirePart {
  return { type: "text", text, state: "done" };
}

/**
 * The bytes the content mocks serve; the media type is the attachment's. ASCII on purpose: the
 * mocked XHR path (axios → MSW's interceptor) round-trips a blob body through text, so a real
 * PNG signature would come back re-encoded and its size would not match.
 */
export const ATTACHMENT_BYTES = new TextEncoder().encode("PNG.");

/**
 * An upload (`AttachmentOut`): a small PNG unless overridden. Nullable fields come as `null`,
 * as the backend sends them; `url` is the bearer-protected content route.
 */
export function makeAttachment(overrides: Partial<Attachment> = {}): Attachment {
  const id = overrides.id ?? `att-${counter++}`;
  return {
    id,
    teamId: "team-1",
    filename: "photo.png",
    mediaType: "image/png",
    sizeBytes: ATTACHMENT_BYTES.byteLength,
    kind: "image",
    textChars: null,
    extractionError: null,
    messageId: null,
    url: `/api/attachments/${id}/content`,
    createdAt: NOW,
    ...overrides,
  };
}

/** The `kind` the backend derives from a media type (the upload mock mirrors it). */
export function attachmentKind(mediaType: string): Attachment["kind"] {
  if (mediaType.startsWith("image/")) return "image";
  if (mediaType === "application/pdf") return "pdf";
  if (mediaType.endsWith("wordprocessingml.document")) return "docx";
  return "text";
}

/** A persisted `file` part (`FilePartOut`), as a message claims an attachment. */
export function filePart(attachment: Attachment): WirePart {
  return {
    type: "file",
    mediaType: attachment.mediaType,
    filename: attachment.filename,
    url: attachment.url,
    attachmentId: attachment.id,
  };
}

type MessageOverrides = Partial<WireMessage> & Pick<WireMessage, "role"> & { text?: string };

/** A persisted message (`MessageOut`); `text` is shorthand for one done text part. */
export function makeMessage({ text, ...overrides }: MessageOverrides): WireMessage {
  const position = counter++;
  return {
    id: `msg-${position}`,
    conversationId: "conv-1",
    position,
    parts: text === undefined ? [] : [textPart(text)],
    createdAt: NOW,
    updatedAt: NOW,
    ...overrides,
  };
}

/** `GET /api/conversations/{id}`: the row plus its messages (the assistant message of an active run omitted). */
export function makeConversationDetail({
  conversation = {},
  messages = [],
}: {
  conversation?: Partial<Conversation>;
  messages?: WireMessage[];
} = {}): ConversationDetail {
  const row = makeConversation(conversation);
  return {
    conversation: row,
    messages: messages.map((message) => ({ ...message, conversationId: row.id })),
  };
}
