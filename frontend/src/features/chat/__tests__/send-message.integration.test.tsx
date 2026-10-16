import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import App from "@/App";
import type { CreateMessageRequest } from "@/features/chat/types";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { APP_NAME } from "@/shared/constants/app";
import { DEFAULT_MODEL_ID, makeConversation, makeModel, makeRun } from "@/test/msw/fixtures/chat";
import { refusalRun, textRun, titleChunk } from "@/test/msw/fixtures/run-chunks";
import { CONVERSATION_ID, restingConversationDetail } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { mockRunEvents, runEventsResponse } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

const THREAD_ROUTE = `/app/teams/team-1/chat/${CONVERSATION_ID}`;

describe("sending a message", () => {
  it("posts the text with the composer's run options, streams the answer and applies the title", async () => {
    const user = userEvent.setup();
    const bodies: CreateMessageRequest[] = [];
    const chunks = textRun({ content: "17 × 23 = 391." });
    chunks.splice(1, 0, titleChunk("Multiplication help"));
    // The worker persists the generated title before it streams the chunk, so the refetch that
    // follows `onFinish` sees it too.
    let title = "Hello there";
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATIONS, ({ params }) =>
        HttpResponse.json({
          items: [makeConversation({ id: CONVERSATION_ID, teamId: params.team_id, title })],
        })
      ),
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATION, () => {
        const detail = restingConversationDetail();
        return HttpResponse.json({ ...detail, conversation: { ...detail.conversation, title } });
      }),
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request, params }) => {
        bodies.push(await request.json());
        return HttpResponse.json(makeRun({ id: "run-1", conversationId: params.conversation_id }), {
          status: 201,
        });
      }),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () => {
        title = "Multiplication help";
        return runEventsResponse(chunks);
      })
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    // The persisted exchange is on screen before anything is sent.
    expect(await screen.findByText("Hello! How can I help?")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Hello there" })).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Message" }), "What is 17*23?");
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("17 × 23 = 391.")).toBeInTheDocument();
    expect(bodies).toEqual([
      {
        parts: [{ type: "text", text: "What is 17*23?" }],
        model: DEFAULT_MODEL_ID,
        mode: "chat",
        tools: { webSearch: true, code: false },
      },
    ]);
    // The user's message is in the thread and the answer is one assistant message; both make
    // up the latest turn, the block pinned to the top of the viewport while the answer comes.
    expect(screen.getByText("What is 17*23?")).toBeInTheDocument();
    expect(screen.getAllByTestId("message-assistant")).toHaveLength(2);
    const latestTurn = screen.getByTestId("latest-turn");
    expect(latestTurn).toHaveTextContent("What is 17*23?");
    expect(latestTurn).toHaveTextContent("17 × 23 = 391.");
    expect(latestTurn).not.toHaveTextContent("Hello! How can I help?");
    // Copy under the finished answer puts its text on the clipboard (user-event's stub; its
    // `readText` cannot read back the Node-realm blob it wrote, so the write is what is checked).
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    await user.click(within(latestTurn).getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("17 × 23 = 391."));
    // The transient `data-conversation-title` reached the heading, the tab title and the sidebar.
    expect(await screen.findByRole("heading", { name: "Multiplication help" })).toBeInTheDocument();
    expect(document.title).toBe(`Multiplication help · ${APP_NAME}`);
    expect(screen.getByRole("link", { name: /Multiplication help/ })).toBeInTheDocument();
    // Back to ready: the composer was cleared, so Submit is disabled again.
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled());
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
  });

  it("disables Search for a model that cannot search and never sends it as on", async () => {
    const user = userEvent.setup();
    const bodies: CreateMessageRequest[] = [];
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.MODELS, () =>
        HttpResponse.json([makeModel({ isDefault: true, webSearch: false })])
      ),
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request, params }) => {
        bodies.push(await request.json());
        return HttpResponse.json(makeRun({ id: "run-1", conversationId: params.conversation_id }), {
          status: 201,
        });
      })
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    // Until the catalog has loaded the remembered toggle (on) stands; then the model decides.
    const search = await screen.findByRole("button", { name: "Search" });
    await waitFor(() => expect(search).toBeDisabled());
    expect(search).toHaveAttribute("aria-pressed", "false");
    expect(search).toHaveAttribute("title", "Web search is not available for this model");
    expect(screen.getByRole("button", { name: "Code" })).toBeEnabled();

    await user.type(screen.getByRole("textbox", { name: "Message" }), "Hi");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]?.tools).toEqual({ webSearch: false, code: false });
  });

  it("renders a refusal as a notice, not an error", async () => {
    const user = userEvent.setup();
    server.use(mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () => runEventsResponse(refusalRun())));
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    await user.type(await screen.findByRole("textbox", { name: "Message" }), "Do the thing");
    await user.keyboard("{Enter}");

    const notice = await screen.findByRole("note");
    expect(notice).toHaveTextContent("The assistant declined to answer (policy).");
    expect(notice).toHaveTextContent("That request is out of scope.");
    expect(screen.queryByRole("alert")).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument());
  });

  it("shows the backend's rejection and keeps the thread usable", async () => {
    const user = userEvent.setup();
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, () =>
        HttpResponse.json(
          {
            error: "A response is already being generated",
            code: "CONFLICT",
            statusCode: 409,
            correlationId: "c-1",
          },
          { status: 409 }
        )
      )
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    await user.type(await screen.findByRole("textbox", { name: "Message" }), "Again?");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("A response is already being generated")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() =>
      expect(screen.queryByText("A response is already being generated")).not.toBeInTheDocument()
    );
    // The optimistic user message stays; the answer never came.
    expect(screen.getByText("Again?")).toBeInTheDocument();
    expect(screen.getAllByTestId("message-assistant")).toHaveLength(1);
  });
});
