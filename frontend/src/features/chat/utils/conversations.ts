import type { Conversation } from "../types";

/** What the sidebar and header show for a conversation: its title, or a placeholder until one is generated. */
export function conversationTitle(conversation: Pick<Conversation, "title">): string {
  return conversation.title ?? "New conversation";
}

/** ChatGPT's sidebar sections, in order. */
const LABELS = ["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"] as const;

type ConversationGroupLabel = (typeof LABELS)[number];

export interface ConversationGroup {
  label: ConversationGroupLabel;
  items: Conversation[];
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** The section of a moment, counted in local days back from the start of today. */
function labelFor(at: number, startOfToday: number): ConversationGroupLabel {
  if (at >= startOfToday) {
    return "Today";
  }
  if (at >= startOfToday - DAY_MS) {
    return "Yesterday";
  }
  if (at >= startOfToday - 7 * DAY_MS) {
    return "Previous 7 days";
  }
  if (at >= startOfToday - 30 * DAY_MS) {
    return "Previous 30 days";
  }
  return "Older";
}

/** Bucket conversations (already newest-first from the backend) by the local day of their last message. */
export function groupConversationsByDay(
  conversations: readonly Conversation[],
  now: Date = new Date()
): ConversationGroup[] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const buckets = new Map<ConversationGroupLabel, Conversation[]>(
    LABELS.map((label) => [label, []])
  );
  for (const conversation of conversations) {
    const label = labelFor(new Date(conversation.lastMessageAt).getTime(), startOfToday);
    buckets.get(label)?.push(conversation);
  }
  return LABELS.map((label) => ({ label, items: buckets.get(label) ?? [] })).filter(
    (group) => group.items.length > 0
  );
}
