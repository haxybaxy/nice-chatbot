import { useChat } from "@ai-sdk/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { QUERY_KEYS } from "@/shared/constants/query-keys";
import { ApiError } from "@/shared/services/api-error";

import { conversationQueryOptions, patchConversationCaches } from "./use-conversations";
import { chatService } from "../services/chat.service";
import { ConversationRunTransport } from "../services/conversation-run-transport";
import type { ChatMessage, ConversationDetail, Run, RunRequestOptions } from "../types";
import { toChatMessage } from "../utils/wire-parts";

interface UseConversationChatOptions {
  teamId: string;
  /** The persisted thread the component mounted with; later refetches do not reset `useChat`. */
  detail: ConversationDetail;
  /** Read at send time (the composer's current choices). */
  getRunOptions: () => RunRequestOptions;
}

/**
 * The live thread of one conversation: `useChat` over `ConversationRunTransport`.
 *
 * This is the one place server state is not a TanStack Query cache — `useChat` owns the
 * messages while a response streams (see CLAUDE.md). The query side stays in sync around it:
 * the thread mounts from the persisted `detail`, resumes when a run was active, patches the
 * title the run streams into the list/detail caches, invalidates both when a response
 * finishes, and refetches the persisted thread when a resume finds the run already finished.
 */
export function useConversationChat({ teamId, detail, getRunOptions }: UseConversationChatOptions) {
  const conversationId = detail.conversation.id;
  const queryClient = useQueryClient();
  // Frozen at mount: `useChat` keys its instance by `id`, so later `detail` refetches must not
  // flip `resume` or feed new initial messages into a thread that is already live.
  const [initialMessages] = useState(() => detail.messages.map(toChatMessage));
  const [resume] = useState(detail.conversation.activeRun != null);
  const [activeRun, setActiveRun] = useState<Run | null>(detail.conversation.activeRun ?? null);

  // One transport per conversation: it owns the socket, so it is created once and its
  // callbacks are refreshed through `update()` below rather than by recreating it.
  const transport = useMemo(
    () =>
      new ConversationRunTransport({
        conversationId,
        getRunOptions: () => ({}),
        onRunChange: setActiveRun,
      }),
    [conversationId]
  );
  useEffect(() => () => transport.close(), [transport]);

  const chat = useChat<ChatMessage>({
    id: conversationId,
    transport,
    messages: initialMessages,
    resume,
    throttle: 50,
    onData: (part) => {
      if (part.type === "data-conversation-title") {
        patchConversationCaches(queryClient, {
          ...detail.conversation,
          id: conversationId,
          teamId,
          title: part.data.title,
        });
      }
    },
    onFinish: () => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.chat.conversations(teamId) });
      void queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.chat.conversation(conversationId),
      });
    },
    onError: (error) => {
      toast.error(error.message);
    },
  });

  // After every render: the composer's latest choices, and the reaction to a resume that found
  // no run (the response finished while we were away, so the persisted thread — now including
  // the assistant message — is the truth).
  const { setMessages } = chat;
  useEffect(() => {
    transport.update({
      getRunOptions,
      onReconnectMiss: () => {
        void queryClient
          .fetchQuery(conversationQueryOptions(conversationId))
          .then((fresh) => setMessages(fresh.messages.map(toChatMessage)))
          .catch(() => {
            // The next mount reloads the thread; nothing to do here.
          });
      },
    });
  });

  const cancelRun = useMutation({
    mutationFn: (runId: string) => chatService.cancelRun(conversationId, runId),
  });
  const { stop: stopChat } = chat;
  const stop = useCallback(async () => {
    const run = transport.run;
    await stopChat();
    if (!run) {
      return;
    }
    try {
      await cancelRun.mutateAsync(run.id);
    } catch (error) {
      // Already finished (404) or already stopping (409): nothing left to cancel.
      if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        return;
      }
      toast.error(error instanceof Error ? error.message : "Could not stop the response.");
    }
  }, [transport, stopChat, cancelRun]);

  const { sendMessage } = chat;
  const send = useCallback((text: string) => sendMessage({ text }), [sendMessage]);

  const { clearError, resumeStream } = chat;
  const reconnect = useCallback(() => {
    clearError();
    void resumeStream();
  }, [clearError, resumeStream]);

  return {
    messages: chat.messages,
    status: chat.status,
    error: chat.error,
    /** The run being streamed, if any; set from mount when the conversation had one. */
    activeRun,
    /** Whether this mount picked up a run that was already in progress. */
    resumed: resume,
    send,
    stop,
    reconnect,
    clearError,
  };
}
