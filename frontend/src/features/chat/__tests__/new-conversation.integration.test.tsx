import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import type { CreateConversationRequest } from "@/features/chat/types";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import {
  DEFAULT_MODEL_ID,
  makeConversation,
  makeConversationDetail,
  makeMessage,
  makeRun,
} from "@/test/msw/fixtures/chat";
import { errorResponse } from "@/test/msw/fixtures/error";
import { textRun } from "@/test/msw/fixtures/run-chunks";
import { NEW_CONVERSATION_ID } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { mockRunEvents, runEventsResponse } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

describe("starting a conversation", () => {
  it("creates it with the first message, navigates to it and resumes the queued run", async () => {
    const user = userEvent.setup();
    const creates: CreateConversationRequest[] = [];
    const activeRunChecks: string[] = [];
    const eventStreams: string[] = [];
    const activeRun = makeRun({
      id: "run-new",
      conversationId: NEW_CONVERSATION_ID,
      status: "running",
    });
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.CONVERSATIONS, async ({ request, params }) => {
        creates.push(await request.json());
        return HttpResponse.json(
          makeConversation({
            id: NEW_CONVERSATION_ID,
            teamId: params.team_id,
            title: undefined,
            activeRun,
          }),
          { status: 201 }
        );
      }),
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATION, ({ params }) =>
        params.conversation_id === NEW_CONVERSATION_ID
          ? HttpResponse.json(
              makeConversationDetail({
                conversation: { id: NEW_CONVERSATION_ID, title: undefined, activeRun },
                // The assistant message of the active run is not persisted yet.
                messages: [makeMessage({ id: "msg-u1", role: "user", text: "Hello?" })],
              })
            )
          : errorResponse(404, "NOT_FOUND")
      ),
      mockApi.get(API_ENDPOINTS.CHAT.ACTIVE_RUN, ({ params }) => {
        activeRunChecks.push(params.conversation_id);
        return HttpResponse.json(activeRun);
      }),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, ({ params }) => {
        eventStreams.push(String(params["run_id"]));
        return runEventsResponse(textRun({ content: "Hi! I'm here." }));
      })
    );
    renderWithProviders(<App />, { route: "/app/teams/team-1/chat" });

    expect(await screen.findByRole("heading", { name: "New chat" })).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Hello?");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("Hi! I'm here.")).toBeInTheDocument();
    expect(creates).toEqual([
      {
        message: {
          parts: [{ type: "text", text: "Hello?" }],
          model: DEFAULT_MODEL_ID,
          mode: "chat",
          tools: { webSearch: true, code: false },
        },
      },
    ]);
    // The thread mounted with `resume`: it asked for the active run and replayed its events.
    expect(activeRunChecks).toEqual([NEW_CONVERSATION_ID]);
    expect(eventStreams).toEqual(["run-new"]);
    expect(screen.getByText("Hello?")).toBeInTheDocument();
    expect(screen.getAllByTestId("message-assistant")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "New conversation" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText(/picking up where it left off/)).not.toBeInTheDocument()
    );
  });

  it("keeps the text and shows the error when the conversation cannot be created", async () => {
    const user = userEvent.setup();
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.CONVERSATIONS, () =>
        errorResponse(400, "BAD_REQUEST", "Unknown model")
      )
    );
    renderWithProviders(<App />, { route: "/app/teams/team-1/chat" });

    await user.type(await screen.findByRole("textbox", { name: "Message" }), "Hello?");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("Unknown model")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "New chat" })).toBeInTheDocument();
  });
});
