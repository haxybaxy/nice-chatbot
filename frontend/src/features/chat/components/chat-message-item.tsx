import { isFileUIPart, isTextUIPart } from "ai";

import { Message, MessageContent } from "@/shared/components/ai-elements/message";

import { AssistantMessage } from "./assistant-message";
import type { ChatMessage } from "../types";
import { FilePart } from "./parts/file-part";

interface ChatMessageItemProps {
  message: ChatMessage;
  /** This message is the one the current response is being written into. */
  isStreaming: boolean;
}

/** One row of the thread: the user's files and text on the right, the assistant's parts on the left. */
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
          <UserMessage message={message} />
        )}
      </MessageContent>
    </Message>
  );
}

/** Attachments first (the order the SDK and the backend keep them in), then the text. */
function UserMessage({ message }: { message: ChatMessage }) {
  const files = message.parts.filter(isFileUIPart);
  const text = message.parts
    .filter(isTextUIPart)
    .map((part) => part.text)
    .join("");
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
