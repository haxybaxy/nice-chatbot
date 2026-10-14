import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { ApiError, apiClient } from "@/shared/services/api-client";

import type {
  Attachment,
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
 * `/api/conversations/*`, plus the attachments (multipart up, bytes down). The run event
 * stream is not here: `ConversationRunTransport` opens it through `openEventStream`
 * (`shared/services/sse-client.ts`).
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

  // ── Attachments ──────────────────────────────────────────────────────────

  /**
   * Upload one file for the team (multipart field `file`). 400 `BAD_REQUEST` for an unsupported
   * type or a file over the limit, 404 for a team the caller is not in. The attachment belongs
   * to the uploader until a message claims it.
   */
  uploadAttachment(
    teamId: string,
    file: File,
    { signal }: { signal?: AbortSignal } = {}
  ): Promise<Attachment> {
    const form = new FormData();
    form.append("file", file, file.name);
    return apiClient.upload(API_ENDPOINTS.ATTACHMENTS.UPLOAD, form, {
      path: { team_id: teamId },
      signal,
    });
  }

  /** The attachment's metadata; visible to every member of its team. */
  getAttachment(attachmentId: string): Promise<Attachment> {
    return apiClient.get(API_ENDPOINTS.ATTACHMENTS.ATTACHMENT, {
      path: { attachment_id: attachmentId },
    });
  }

  /** The stored bytes under their media type (bearer-protected: shown through an object URL). */
  getAttachmentBlob(
    attachmentId: string,
    { signal }: { signal?: AbortSignal } = {}
  ): Promise<Blob> {
    return apiClient.blob(API_ENDPOINTS.ATTACHMENTS.CONTENT, {
      path: { attachment_id: attachmentId },
      signal,
    });
  }

  /** Withdraw an upload that no message carries yet (409 once sent, 403 for another member's). */
  async deleteAttachment(attachmentId: string): Promise<void> {
    await apiClient.delete(API_ENDPOINTS.ATTACHMENTS.ATTACHMENT, {
      path: { attachment_id: attachmentId },
    });
  }
}

export const chatService = new ChatService();
