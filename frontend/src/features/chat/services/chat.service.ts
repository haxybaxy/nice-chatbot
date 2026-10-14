import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { ApiError, apiClient } from "@/shared/services/api-client";

import type {
  ChatModel,
  Conversation,
  ConversationDetail,
  ConversationPage,
  CreateConversationRequest,
  CreateMessageRequest,
  Run,
  UpdateConversationRequest,
} from "../types";

/**
 * Chat service — the JSON side of `/api/chat/*`, `/api/teams/{id}/conversations` and
 * `/api/conversations/*`. The run event stream is not here: `ConversationRunTransport` opens it
 * through `openEventStream` (`shared/services/sse-client.ts`).
 */
class ChatService {
  listModels(): Promise<ChatModel[]> {
    return apiClient.get(API_ENDPOINTS.CHAT.MODELS);
  }

  /** One page of a team's conversations, newest first; pass the previous page's `nextCursor`. */
  listConversations(teamId: string, cursor?: string): Promise<ConversationPage> {
    return apiClient.get(API_ENDPOINTS.CHAT.CONVERSATIONS, {
      path: { team_id: teamId },
      query: cursor ? { cursor } : {},
    });
  }

  /** Create a conversation; with `message`, its first run is queued and comes back as `activeRun`. */
  createConversation(teamId: string, body: CreateConversationRequest): Promise<Conversation> {
    return apiClient.post(API_ENDPOINTS.CHAT.CONVERSATIONS, body, { path: { team_id: teamId } });
  }

  getConversation(conversationId: string): Promise<ConversationDetail> {
    return apiClient.get(API_ENDPOINTS.CHAT.CONVERSATION, {
      path: { conversation_id: conversationId },
    });
  }

  updateConversation(
    conversationId: string,
    body: UpdateConversationRequest
  ): Promise<Conversation> {
    return apiClient.patch(API_ENDPOINTS.CHAT.CONVERSATION, body, {
      path: { conversation_id: conversationId },
    });
  }

  /** 409 while a run is active — stop it first. */
  async deleteConversation(conversationId: string): Promise<void> {
    await apiClient.delete(API_ENDPOINTS.CHAT.CONVERSATION, {
      path: { conversation_id: conversationId },
    });
  }

  /** Persist a user message and queue the run that answers it (409 while one is active). */
  sendMessage(conversationId: string, body: CreateMessageRequest): Promise<Run> {
    return apiClient.post(API_ENDPOINTS.CHAT.MESSAGES, body, {
      path: { conversation_id: conversationId },
    });
  }

  /** The queued or running run, or `null` — the backend answers 404 when there is none. */
  async getActiveRun(conversationId: string): Promise<Run | null> {
    try {
      return await apiClient.get(API_ENDPOINTS.CHAT.ACTIVE_RUN, {
        path: { conversation_id: conversationId },
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  }

  /** Ask the worker to stop; it writes the `abort` chunk and the run ends `cancelled`. */
  async cancelRun(conversationId: string, runId: string): Promise<void> {
    await apiClient.post(API_ENDPOINTS.CHAT.CANCEL_RUN, undefined, {
      path: { conversation_id: conversationId, run_id: runId },
    });
  }
}

export const chatService = new ChatService();
