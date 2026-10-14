import { isTextUIPart } from "ai";

import { Message, MessageContent } from "@/shared/components/ai-elements/message";

import { AssistantMessage } from "./assistant-message";
import type { ChatMessage } from "../types";

interface ChatMessageItemProps {
  message: ChatMessage;
  /** This message is the one the current response is being written into. */
  isStreaming: boolean;
}

/** One row of the thread: the user's text on the right, the assistant's parts on the left. */
export function ChatMessageItem({ message, isStreaming }: ChatMessageItemProps) {
  return (
    <Message
      from={message.role}
      data-testid={`message-${message.role}`}
      data-message-id={message.id}
    >
      <MessageContent>
        {message.role === "assistant" ? (
          <AssistantMessage message={message} isStreaming={isStreaming} />
        ) : (
          <p className="whitespace-pre-wrap">
            {message.parts
              .filter(isTextUIPart)
              .map((part) => part.text)
              .join("")}
          </p>
        )}
      </MessageContent>
    </Message>
  );
}
