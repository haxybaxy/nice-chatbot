import { isFileUIPart, isTextUIPart } from "ai";

import { Message, MessageContent } from "@/shared/components/ai-elements/message";

import { AssistantActions } from "./assistant-actions";
import { AssistantMessage } from "./assistant-message";
import type { ChatMessage } from "../types";
import { FilePart } from "./parts/file-part";

interface ChatMessageItemProps {
  message: ChatMessage;
  /** This message is the one the current response is being written into. */
  isStreaming: boolean;
  /** The thread's last message: its actions stay visible instead of waiting for a hover. */
  isLast: boolean;
}

/** The message's text parts, joined — what a user message shows and what Copy takes. */
function messageText(message: ChatMessage): string {
  return message.parts
    .filter(isTextUIPart)
    .map((part) => part.text)
    .join("\n\n");
}

/**
 * One row of the thread, as ChatGPT lays it out: the user's files and text in a bubble on the
 * right, the assistant's parts as plain full-width prose on the left with its actions under.
 */
export function ChatMessageItem({ message, isStreaming, isLast }: ChatMessageItemProps) {
  const text = messageText(message);
  return (
    <Message
      from={message.role}
      className="max-w-full"
      data-testid={`message-${message.role}`}
      data-message-id={message.id}
    >
      <MessageContent className="text-base leading-7 group-[.is-assistant]:w-full group-[.is-user]:max-w-[85%] group-[.is-user]:rounded-3xl group-[.is-user]:px-5 group-[.is-user]:py-2.5 sm:group-[.is-user]:max-w-[70%]">
        {message.role === "assistant" ? (
          <AssistantMessage message={message} isStreaming={isStreaming} />
        ) : (
          <UserMessage message={message} text={text} />
        )}
      </MessageContent>
      {message.role === "assistant" && !isStreaming && text && (
        <AssistantActions text={text} isLast={isLast} />
      )}
    </Message>
  );
}

/** Attachments first (the order the SDK and the backend keep them in), then the text. */
function UserMessage({ message, text }: { message: ChatMessage; text: string }) {
  const files = message.parts.filter(isFileUIPart);
  return (
    <>
      {files.length > 0 && (
        <div className="flex flex-wrap gap-2" data-testid="message-files">
          {files.map((part, index) => (
            <FilePart key={`${part.url}#${index}`} part={part} />
          ))}
        </div>
      )}
      {text && <p className="whitespace-pre-wrap">{text}</p>}
    </>
  );
}
