import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { makeConversationDetail, makeMessage, makeRun } from "@/test/msw/fixtures/chat";
import { errorResponse } from "@/test/msw/fixtures/error";
import { ASSISTANT_MESSAGE_ID, textRun } from "@/test/msw/fixtures/run-chunks";
import { CONVERSATION_ID } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { mockRunEvents, runEventsResponse } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

const THREAD_ROUTE = `/app/teams/team-1/chat/${CONVERSATION_ID}`;

const activeRun = makeRun({ id: "run-live", conversationId: CONVERSATION_ID, status: "running" });

/** The thread as the backend serves it mid-run: the user message, no assistant message yet. */
function detailWithActiveRun() {
  return makeConversationDetail({
    conversation: { id: CONVERSATION_ID, activeRun },
    messages: [makeMessage({ id: "msg-u1", role: "user", text: "Tell me something" })],
  });
}

describe("resuming a run", () => {
  it("replays the active run from the start into exactly one assistant message", async () => {
    const streams: string[] = [];
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATION, () => HttpResponse.json(detailWithActiveRun())),
      mockApi.get(API_ENDPOINTS.CHAT.ACTIVE_RUN, () => HttpResponse.json(activeRun)),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, ({ params }) => {
        streams.push(String(params["run_id"]));
        return runEventsResponse(textRun({ content: "Something interesting." }));
      })
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    expect(await screen.findByText("Something interesting.")).toBeInTheDocument();
    expect(streams).toEqual(["run-live"]);
    const assistant = screen.getAllByTestId("message-assistant");
    expect(assistant).toHaveLength(1);
    // `start.messageId` is the persisted id, so the message carries it.
    expect(assistant[0]).toHaveAttribute("data-message-id", ASSISTANT_MESSAGE_ID);
    await waitFor(() =>
      expect(screen.queryByText(/picking up where it left off/)).not.toBeInTheDocument()
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument());
  });

  it("refetches the persisted thread when the run finished before the reconnect", async () => {
    let detailFetches = 0;
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATION, () => {
        detailFetches += 1;
        return HttpResponse.json(
          detailFetches === 1
            ? detailWithActiveRun()
            : makeConversationDetail({
                conversation: { id: CONVERSATION_ID },
                messages: [
                  makeMessage({ id: "msg-u1", role: "user", text: "Tell me something" }),
                  makeMessage({
                    id: ASSISTANT_MESSAGE_ID,
                    role: "assistant",
                    text: "Already done.",
                  }),
                ],
              })
        );
      }),
      mockApi.get(API_ENDPOINTS.CHAT.ACTIVE_RUN, () => errorResponse(404, "NOT_FOUND", "No run")),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () => errorResponse(404, "NOT_FOUND"))
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    expect(await screen.findByText("Already done.")).toBeInTheDocument();
    expect(screen.getAllByTestId("message-assistant")).toHaveLength(1);
    expect(detailFetches).toBe(2);
  });

  it("offers Reconnect when the stream cannot be opened, and the replay replaces nothing twice", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATION, () => HttpResponse.json(detailWithActiveRun())),
      mockApi.get(API_ENDPOINTS.CHAT.ACTIVE_RUN, () => HttpResponse.json(activeRun)),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () => {
        attempts += 1;
        return attempts === 1
          ? errorResponse(503, "SERVICE_UNAVAILABLE", "Event log unavailable")
          : runEventsResponse(textRun({ content: "Second time lucky." }));
      })
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    expect(await screen.findByText("Server error. Please try again later.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reconnect" }));

    expect(await screen.findByText("Second time lucky.")).toBeInTheDocument();
    expect(attempts).toBe(2);
    expect(screen.getAllByTestId("message-assistant")).toHaveLength(1);
  });
});
