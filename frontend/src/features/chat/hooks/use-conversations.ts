import {
  type InfiniteData,
  type QueryClient,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { QUERY_KEYS } from "@/shared/constants/query-keys";

import { chatService } from "../services/chat.service";
import type {
  Conversation,
  ConversationDetail,
  ConversationPage,
  CreateConversationRequest,
} from "../types";

/** A team's conversations, newest first, one page per `nextCursor`. */
export function useConversations(teamId: string) {
  return useInfiniteQuery({
    queryKey: QUERY_KEYS.chat.conversations(teamId),
    queryFn: ({ pageParam }) => chatService.listConversations(teamId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}

/** Shared with `useConversationChat`, which refetches the thread imperatively after a missed resume. */
export function conversationQueryOptions(conversationId: string) {
  return queryOptions({
    queryKey: QUERY_KEYS.chat.conversation(conversationId),
    queryFn: () => chatService.getConversation(conversationId),
  });
}

/**
 * One conversation with its persisted messages. While a run is active the assistant message
 * being produced is not in `messages` — `useChat` rebuilds it from the replayed stream.
 */
export function useConversation(conversationId: string) {
  return useQuery(conversationQueryOptions(conversationId));
}

export function useCreateConversation(teamId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: CreateConversationRequest) => chatService.createConversation(teamId, body),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.chat.conversations(teamId) }),
  });
}

export function useRenameConversation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ conversationId, title }: { conversationId: string; title: string }) =>
      chatService.updateConversation(conversationId, { title }),
    onSuccess: (conversation) => {
      patchConversationCaches(queryClient, conversation);
      return queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.chat.conversations(conversation.teamId),
      });
    },
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ conversationId }: { conversationId: string; teamId: string }) =>
      chatService.deleteConversation(conversationId),
    onSuccess: (_, { conversationId, teamId }) => {
      queryClient.removeQueries({ queryKey: QUERY_KEYS.chat.conversation(conversationId) });
      return queryClient.invalidateQueries({ queryKey: QUERY_KEYS.chat.conversations(teamId) });
    },
  });
}

/**
 * Apply a conversation's new row to the list pages and the detail cache without a refetch —
 * used for a rename and for the title the run streams (`data-conversation-title`).
 */
export function patchConversationCaches(
  queryClient: QueryClient,
  conversation: Conversation
): void {
  queryClient.setQueryData<InfiniteData<ConversationPage>>(
    QUERY_KEYS.chat.conversations(conversation.teamId),
    (data) =>
      data && {
        ...data,
        pages: data.pages.map((page) => ({
          ...page,
          items: page.items.map((item) =>
            item.id === conversation.id ? { ...item, ...conversation } : item
          ),
        })),
      }
  );
  queryClient.setQueryData<ConversationDetail>(
    QUERY_KEYS.chat.conversation(conversation.id),
    (detail) => detail && { ...detail, conversation: { ...detail.conversation, ...conversation } }
  );
}
