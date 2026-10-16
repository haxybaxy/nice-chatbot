import { useState } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/shared/components/ai-elements/conversation";
import { cn } from "@/shared/utils";

import { ChatComposer } from "./chat-composer";
import { ChatErrorAlert } from "./chat-error-alert";
import { ChatMessageItem } from "./chat-message-item";
import { ResponsePending } from "./response-pending";
import { useChatModels } from "../hooks/use-chat-models";
import { toRunRequestOptions, useComposerSettings } from "../hooks/use-composer-settings";
import { useConversationChat } from "../hooks/use-conversation-chat";
import type { ChatMessage, ConversationDetail } from "../types";

interface ChatThreadProps {
  teamId: string;
  /** The persisted conversation this thread mounted with (remount — `key` — to switch). */
  detail: ConversationDetail;
}

/**
 * The messages before the latest turn, and the latest turn: from the last user message sent
 * since the thread mounted (index ≥ `mountedCount`) to the end. Empty when nothing was sent
 * from this mount — an old conversation opened fresh has no turn to pin.
 */
function splitLatestTurn(
  messages: readonly ChatMessage[],
  mountedCount: number
): { earlier: readonly ChatMessage[]; latest: readonly ChatMessage[] } {
  for (let index = messages.length - 1; index >= mountedCount; index -= 1) {
    if (messages[index]?.role === "user") {
      return { earlier: messages.slice(0, index), latest: messages.slice(index) };
    }
  }
  return { earlier: messages, latest: [] };
}

/**
 * The live thread: messages (scrolling, stuck to the bottom), the error, the composer.
 *
 * ChatGPT's send behaviour: the turn sent from this mount is wrapped in a block at least as
 * tall as the thread's viewport (`100cqh` — the `Conversation` is a size container), so when
 * the thread sticks to the bottom the user's message sits at the top with room for its answer
 * below; once the answer outgrows that room the thread follows it as usual. The pending dot —
 * nothing has arrived yet, including the wait while a reopened run reconnects — sits in that
 * block, where the answer will appear.
 */
export function ChatThread({ teamId, detail }: ChatThreadProps) {
  const models = useChatModels();
  const catalog = models.data ?? [];
  const [settings, updateSettings] = useComposerSettings();
  const runOptions = toRunRequestOptions(settings, catalog);
  const chat = useConversationChat({ teamId, detail, getRunOptions: () => runOptions });
  // The messages the thread mounted with; anything after them was sent from here.
  const [mountedCount] = useState(chat.messages.length);
  const isBusy = chat.status === "submitted" || chat.status === "streaming";
  const lastMessage = chat.messages.at(-1);
  // The `start` chunk creates the assistant message, and from then on the message's own
  // activity line (`AssistantActivity`) says what is happening — one indicator at a time.
  const awaitingResponse = chat.status === "submitted" && lastMessage?.role !== "assistant";
  const { earlier, latest } = splitLatestTurn(chat.messages, mountedCount);

  const renderMessage = (message: ChatMessage) => (
    <ChatMessageItem
      key={message.id}
      message={message}
      isStreaming={isBusy && message === lastMessage && message.role === "assistant"}
    />
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Conversation className="min-h-0 flex-1 @container-size">
        <ConversationContent className="mx-auto w-full max-w-3xl gap-6 px-4 pt-6 pb-4">
          {earlier.map(renderMessage)}
          {(latest.length > 0 || awaitingResponse) && (
            <div
              className={cn(
                "flex flex-col gap-6",
                latest.length > 0 && "min-h-[calc(100cqh-2.5rem)]"
              )}
              data-testid="latest-turn"
            >
              {latest.map(renderMessage)}
              {awaitingResponse && <ResponsePending />}
            </div>
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>
      <div className="shrink-0 px-4 pb-4">
        {chat.error && (
          <ChatErrorAlert
            error={chat.error}
            onReconnect={chat.reconnect}
            onDismiss={chat.clearError}
          />
        )}
        <div className="mx-auto w-full max-w-3xl">
          <ChatComposer
            teamId={teamId}
            status={chat.status}
            // Not awaited: `send` resolves when the response has finished streaming, and the
            // composer must clear as soon as the optimistic message is in the thread.
            onSubmit={(message) => {
              void chat.send(message);
            }}
            onStop={() => void chat.stop()}
            settings={settings}
            onSettingsChange={updateSettings}
            models={catalog}
          />
        </div>
      </div>
    </div>
  );
}
