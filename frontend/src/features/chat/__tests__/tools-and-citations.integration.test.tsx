import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import type { CreateMessageRequest } from "@/features/chat/types";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { makeConversationDetail, makeMessage, makeRun, textPart } from "@/test/msw/fixtures/chat";
import {
  NATIVE_SOURCE,
  nativeWebSearchRun,
  SOURCE,
  WEB_SEARCH_QUERY,
  webSearchRun,
} from "@/test/msw/fixtures/run-chunks";
import { CONVERSATION_ID } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { mockRunEvents, runEventsResponse } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

const THREAD_ROUTE = `/app/teams/team-1/chat/${CONVERSATION_ID}`;

/** The chip row under the answer: `Sources · N`, then one favicon + `[n]` + hostname link per source. */
function expectSourceChip({
  url,
  title,
  hostname,
}: {
  url: string;
  title: string;
  hostname: string;
}) {
  const chips = within(screen.getByTestId("source-chips"));
  expect(chips.getByText("Sources · 1")).toBeInTheDocument();
  const chip = chips.getByRole("link");
  expect(within(chip).getByText("[1]")).toHaveAttribute("data-variant", "outline");
  expect(within(chip).getByText(hostname)).toBeInTheDocument();
  expect(chip).toHaveAttribute("href", url);
  expect(chip).toHaveAttribute("title", title);
  expect(chip).toHaveAttribute("target", "_blank");
  const favicon = chip.querySelector("img");
  expect(favicon).toHaveAttribute(
    "src",
    `https://www.google.com/s2/favicons?domain=${hostname}&sz=32`
  );
  expect(favicon).toHaveAttribute("referrerpolicy", "no-referrer");
}

describe("web tools and citations", () => {
  it("sends Search (on by default), renders the search and fetch calls, a clickable [1] and the source chips", async () => {
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

    const search = await screen.findByRole("button", { name: "Search" });
    expect(search).toHaveAttribute("aria-pressed", "true");
    expect(search).toBeEnabled();
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
    expect(screen.queryByText("Built-in search")).toBeNull();

    // The source chips under the answer.
    expectSourceChip({ url: SOURCE.url, title: SOURCE.title, hostname: "docs.python.org" });
  });

  it("renders a model's built-in search: one step, the page it consulted, the inline link as the [1] pill", async () => {
    const user = userEvent.setup();
    server.use(
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () => runEventsResponse(nativeWebSearchRun()))
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    await user.type(
      await screen.findByRole("textbox", { name: "Message" }),
      "What changed in Python 3.14?"
    );
    await user.keyboard("{Enter}");

    // The model's own `[What's New](url?utm_source=…)` is the same pill a `[1]` would be; the
    // tracking parameter stays on the link, the match ignores it.
    const citation = await screen.findByRole("link", { name: "[1]" });
    expect(citation).toHaveAttribute("href", NATIVE_SOURCE.linkUrl);
    expect(citation).toHaveAttribute("data-citation", "1");
    expect(screen.queryByRole("link", { name: "What's New" })).toBeNull();
    expect(screen.getByText(/Python 3.14 adds template strings/)).toBeInTheDocument();

    // The search, collapsed: the consulted page has no title, so its hostname is the link.
    const header = screen.getByText(`Searched for “${WEB_SEARCH_QUERY}”`);
    expect(screen.queryByText("Built-in search")).toBeNull();
    await user.click(header);
    expect(await screen.findByText("Built-in search")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "docs.python.org" })).toHaveAttribute(
      "href",
      SOURCE.url
    );
    expect(screen.queryByText("Fetched docs.python.org")).toBeNull();

    expectSourceChip({ url: SOURCE.url, title: SOURCE.title, hostname: "docs.python.org" });
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
    expectSourceChip({
      url: "https://example.com/nice",
      title: "Nice Chatbot",
      hostname: "example.com",
    });
    expect(screen.getAllByTestId("message-assistant")).toHaveLength(1);
    // Nothing streams, so there is no activity line.
    expect(screen.queryByTestId("assistant-activity")).toBeNull();
  });

  it("renders a persisted built-in search and fetch: 'Read <host>' and the built-in label, no page text", async () => {
    const user = userEvent.setup();
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATION, () =>
        HttpResponse.json(
          makeConversationDetail({
            conversation: { id: CONVERSATION_ID },
            messages: [
              makeMessage({
                id: "msg-a1",
                role: "assistant",
                parts: [
                  { type: "step-start" },
                  {
                    type: "tool-web_search",
                    toolCallId: "ws_1",
                    state: "output-available",
                    providerExecuted: true,
                    input: { query: "python 3.14 | t-strings" },
                    output: { query: "python 3.14 | t-strings", results: [] },
                  },
                  {
                    type: "tool-web_fetch",
                    toolCallId: "wf_1",
                    state: "output-available",
                    providerExecuted: true,
                    input: { url: SOURCE.url },
                    output: {
                      sourceId: null,
                      url: SOURCE.url,
                      title: null,
                      content: "",
                      chars: 0,
                      truncated: false,
                    },
                  },
                  textPart("Template strings arrived."),
                ],
              }),
            ],
          })
        )
      )
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    expect(await screen.findByText("Searched for “python 3.14 · t-strings”")).toBeInTheDocument();
    await user.click(screen.getByText("Read docs.python.org"));
    expect(await screen.findByRole("link", { name: SOURCE.url })).toHaveAttribute(
      "href",
      SOURCE.url
    );
    expect(screen.queryByText(/chars/)).toBeNull();
    await user.click(screen.getByText("Searched for “python 3.14 · t-strings”"));
    expect(await screen.findByText("No results.")).toBeInTheDocument();
    expect(screen.getByText("Built-in search")).toBeInTheDocument();
    expect(screen.queryByTestId("source-chips")).toBeNull();
  });
});
