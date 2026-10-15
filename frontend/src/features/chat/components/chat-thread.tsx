import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/shared/components/ai-elements/conversation";
import { Shimmer } from "@/shared/components/ai-elements/shimmer";

import { ChatComposer } from "./chat-composer";
import { ChatErrorAlert } from "./chat-error-alert";
import { ChatMessageItem } from "./chat-message-item";
import { RunStatusBanner } from "./run-status-banner";
import { useChatModels } from "../hooks/use-chat-models";
import { toRunRequestOptions, useComposerSettings } from "../hooks/use-composer-settings";
import { useConversationChat } from "../hooks/use-conversation-chat";
import type { ConversationDetail } from "../types";

interface ChatThreadProps {
  teamId: string;
  /** The persisted conversation this thread mounted with (remount — `key` — to switch). */
  detail: ConversationDetail;
}

/** The live thread: messages (scrolling, stuck to the bottom), the status banner / error, the composer. */
export function ChatThread({ teamId, detail }: ChatThreadProps) {
  const models = useChatModels();
  const catalog = models.data ?? [];
  const [settings, updateSettings] = useComposerSettings();
  const runOptions = toRunRequestOptions(settings, catalog);
  const chat = useConversationChat({ teamId, detail, getRunOptions: () => runOptions });
  const isBusy = chat.status === "submitted" || chat.status === "streaming";
  const lastMessage = chat.messages.at(-1);
  // "Thinking…" covers the wait before any chunk. The `start` chunk creates the assistant
  // message without flipping the status to `streaming`, and from then on the message's own
  // activity line (`AssistantActivity`) says what is happening — one indicator at a time.
  const awaitingFirstChunk = chat.status === "submitted" && lastMessage?.role !== "assistant";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Conversation className="min-h-0 flex-1">
        <ConversationContent className="mx-auto w-full max-w-3xl">
          {chat.resumed && chat.activeRun && <RunStatusBanner run={chat.activeRun} />}
          {chat.messages.map((message) => (
            <ChatMessageItem
              key={message.id}
              message={message}
              isStreaming={isBusy && message === lastMessage && message.role === "assistant"}
            />
          ))}
          {awaitingFirstChunk && (
            <Shimmer duration={1} className="text-sm">
              Thinking…
            </Shimmer>
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
