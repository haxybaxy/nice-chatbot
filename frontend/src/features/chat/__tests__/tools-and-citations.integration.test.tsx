import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import type { CreateMessageRequest } from "@/features/chat/types";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { makeConversationDetail, makeMessage, makeRun, textPart } from "@/test/msw/fixtures/chat";
import { SOURCE, WEB_SEARCH_QUERY, webSearchRun } from "@/test/msw/fixtures/run-chunks";
import { CONVERSATION_ID } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { mockRunEvents, runEventsResponse } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

const THREAD_ROUTE = `/app/teams/team-1/chat/${CONVERSATION_ID}`;

describe("web tools and citations", () => {
  it("sends the Search toggle, renders the search and fetch calls, the sources and a clickable [1]", async () => {
    const user = userEvent.setup();
    const bodies: CreateMessageRequest[] = [];
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request, params }) => {
        bodies.push(await request.json());
        return HttpResponse.json(makeRun({ id: "run-1", conversationId: params.conversation_id }), {
          status: 201,
        });
      }),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () => runEventsResponse(webSearchRun()))
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    await user.click(await screen.findByRole("button", { name: "Search" }));
    expect(screen.getByRole("button", { name: "Search" })).toHaveAttribute("aria-pressed", "true");
    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "What changed in Python 3.14?"
    );
    await user.keyboard("{Enter}");

    const citation = await screen.findByRole("link", { name: "[1]" });
    expect(citation).toHaveAttribute("href", SOURCE.url);
    expect(citation).toHaveAttribute("data-citation", "1");
    expect(bodies[0]?.tools).toEqual({ webSearch: true, code: false });

    // Both tool calls, collapsed, with their human headers.
    expect(screen.getByText(`Searched for “${WEB_SEARCH_QUERY}”`)).toBeInTheDocument();
    expect(screen.getByText("Fetched docs.python.org")).toBeInTheDocument();
    expect(screen.queryByText("Template strings, deferred annotations and a new REPL.")).toBeNull();
    await user.click(screen.getByText(`Searched for “${WEB_SEARCH_QUERY}”`));
    expect(
      await screen.findByText("Template strings, deferred annotations and a new REPL.")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: SOURCE.title })).toHaveAttribute("href", SOURCE.url);

    // The numbered source list.
    expect(screen.getByText("Used 1 sources")).toBeInTheDocument();
  });

  it("renders a persisted message with tool parts, sources and citations the same way", async () => {
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATION, () =>
        HttpResponse.json(
          makeConversationDetail({
            conversation: { id: CONVERSATION_ID },
            messages: [
              makeMessage({ id: "msg-u1", role: "user", text: "Find it" }),
              makeMessage({
                id: "msg-a1",
                role: "assistant",
                parts: [
                  { type: "step-start" },
                  { type: "reasoning", text: "I should search first.", state: "done" },
                  {
                    type: "tool-web_search",
                    toolCallId: "call-1",
                    state: "output-available",
                    input: { query: "nice chatbot" },
                    output: {
                      query: "nice chatbot",
                      results: [
                        {
                          sourceId: "1",
                          title: "Nice Chatbot",
                          url: "https://example.com/nice",
                          snippet: "A team chat.",
                        },
                      ],
                    },
                  },
                  {
                    type: "source-url",
                    sourceId: "1",
                    url: "https://example.com/nice",
                    title: "Nice Chatbot",
                  },
                  {
                    type: "tool-web_fetch",
                    toolCallId: "call-2",
                    state: "output-error",
                    input: { url: "https://example.com/down" },
                    errorText: "The page could not be fetched",
                  },
                  textPart("Found it [1]. Unknown [9] stays."),
                ],
              }),
            ],
          })
        )
      )
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    expect(await screen.findByRole("link", { name: "[1]" })).toHaveAttribute(
      "href",
      "https://example.com/nice"
    );
    expect(screen.queryByRole("link", { name: "[9]" })).toBeNull();
    expect(screen.getByText("Searched for “nice chatbot”")).toBeInTheDocument();
    expect(screen.getByText("Fetched example.com")).toBeInTheDocument();
    expect(screen.getByText("Thought for a few seconds")).toBeInTheDocument();
    expect(screen.getByText("Used 1 sources")).toBeInTheDocument();
    expect(screen.getAllByTestId("message-assistant")).toHaveLength(1);
  });
});
