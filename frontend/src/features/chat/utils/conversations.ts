import type { Conversation } from "../types";

/** What the sidebar and header show for a conversation: its title, or a placeholder until one is generated. */
export function conversationTitle(conversation: Pick<Conversation, "title">): string {
  return conversation.title ?? "New conversation";
}

type ConversationGroupLabel = "Today" | "Yesterday" | "Earlier";

export interface ConversationGroup {
  label: ConversationGroupLabel;
  items: Conversation[];
}

const DAY_MS = 24 * 60 * 60 * 1000;
const LABELS: readonly ConversationGroupLabel[] = ["Today", "Yesterday", "Earlier"];

/** Bucket conversations (already newest-first from the backend) by the local day of their last message. */
export function groupConversationsByDay(
  conversations: readonly Conversation[],
  now: Date = new Date()
): ConversationGroup[] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfYesterday = startOfToday - DAY_MS;
  const buckets: Record<ConversationGroupLabel, Conversation[]> = {
    Today: [],
    Yesterday: [],
    Earlier: [],
  };
  for (const conversation of conversations) {
    const at = new Date(conversation.lastMessageAt).getTime();
    const label = at >= startOfToday ? "Today" : at >= startOfYesterday ? "Yesterday" : "Earlier";
    buckets[label].push(conversation);
  }
  return LABELS.map((label) => ({ label, items: buckets[label] })).filter(
    (group) => group.items.length > 0
  );
}
