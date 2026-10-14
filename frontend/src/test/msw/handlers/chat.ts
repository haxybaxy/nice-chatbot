import { HttpResponse } from "msw";

import { API_ENDPOINTS } from "@/shared/config/api-endpoints";

import {
  DEFAULT_MODEL_ID,
  DEFAULT_MODELS,
  makeConversation,
  makeConversationDetail,
  makeMessage,
  makeRun,
} from "../fixtures/chat";
import { errorResponse } from "../fixtures/error";
import { textRun } from "../fixtures/run-chunks";
import { mockRunEvents, runEventsResponse } from "../sse";
import { mockApi } from "../typed-http";

/** The one conversation the resting handlers know: a finished user/assistant exchange. */
export const CONVERSATION_ID = "conv-1";
/** What `POST …/conversations` creates. */
export const NEW_CONVERSATION_ID = "conv-new";

export function restingConversationDetail() {
  return makeConversationDetail({
    conversation: { id: CONVERSATION_ID },
    messages: [
      makeMessage({ id: "msg-u1", role: "user", text: "Hi there" }),
      makeMessage({ id: "msg-a0", role: "assistant", text: "Hello! How can I help?" }),
    ],
  });
}

/**
 * Resting-state chat handlers: a catalog of two models, one conversation per team, a queued
 * run for every message, no active run (404), and a short text answer on the event stream.
 */
export const chatHandlers = [
  mockApi.get(API_ENDPOINTS.CHAT.MODELS, () => HttpResponse.json(DEFAULT_MODELS)),

  mockApi.get(API_ENDPOINTS.CHAT.CONVERSATIONS, ({ params }) =>
    HttpResponse.json({
      items: [makeConversation({ id: CONVERSATION_ID, teamId: params.team_id })],
    })
  ),

  mockApi.post(API_ENDPOINTS.CHAT.CONVERSATIONS, async ({ request, params }) => {
    const body = await request.json(); // `CreateConversationIn`, from the spec — no cast
    return HttpResponse.json(
      makeConversation({
        id: NEW_CONVERSATION_ID,
        teamId: params.team_id,
        title: body.title ?? undefined,
        visibility: body.visibility ?? "team",
        activeRun: body.message
          ? makeRun({ id: "run-new", conversationId: NEW_CONVERSATION_ID, mode: body.message.mode })
          : undefined,
      }),
      { status: 201 }
    );
  }),

  mockApi.get(API_ENDPOINTS.CHAT.CONVERSATION, ({ params }) =>
    params.conversation_id === CONVERSATION_ID
      ? HttpResponse.json(restingConversationDetail())
      : errorResponse(404, "NOT_FOUND", "Conversation not found")
  ),

  mockApi.patch(API_ENDPOINTS.CHAT.CONVERSATION, async ({ request, params }) => {
    const body = await request.json(); // `UpdateConversationIn`
    return HttpResponse.json(
      makeConversation({
        id: params.conversation_id,
        ...(body.title !== undefined ? { title: body.title } : {}),
        ...(body.visibility ? { visibility: body.visibility } : {}),
      })
    );
  }),

  mockApi.delete(API_ENDPOINTS.CHAT.CONVERSATION, () => new HttpResponse(null, { status: 204 })),

  mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request, params }) => {
    const body = await request.json(); // `CreateMessageIn`
    return HttpResponse.json(
      makeRun({
        id: "run-1",
        conversationId: params.conversation_id,
        mode: body.mode ?? "chat",
        model: body.model ?? DEFAULT_MODEL_ID,
        options: { webSearch: body.tools?.webSearch ?? false, code: body.tools?.code ?? false },
      }),
      { status: 201 }
    );
  }),

  mockApi.get(API_ENDPOINTS.CHAT.ACTIVE_RUN, () =>
    errorResponse(404, "NOT_FOUND", "No active run")
  ),

  mockApi.get(API_ENDPOINTS.CHAT.RUN, ({ params }) =>
    HttpResponse.json(
      makeRun({ id: params.run_id, conversationId: params.conversation_id, status: "succeeded" })
    )
  ),

  mockApi.post(API_ENDPOINTS.CHAT.CANCEL_RUN, () => new HttpResponse(null, { status: 204 })),

  mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () => runEventsResponse(textRun())),
];
