import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UIMessageChunk } from "ai";
import { describe, expect, it } from "vitest";

import App from "@/App";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { nativeWebFetchRun, WEB_SEARCH_QUERY } from "@/test/msw/fixtures/run-chunks";
import { CONVERSATION_ID } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { controllableRunEvents, mockRunEvents } from "@/test/msw/sse";
import { renderWithProviders } from "@/test/render-with-providers";

const THREAD_ROUTE = `/app/teams/team-1/chat/${CONVERSATION_ID}`;

/** Feeds a script to a controllable stream in slices, each ending at the next chunk of a type. */
function scriptFeeder(chunks: UIMessageChunk[], events: ReturnType<typeof controllableRunEvents>) {
  let cursor = 0;
  return {
    /** Push every chunk up to and including the next one of `type`. */
    through(type: UIMessageChunk["type"]) {
      const end = chunks.findIndex((chunk, index) => index >= cursor && chunk.type === type);
      if (end === -1) {
        throw new Error(`no ${type} chunk after #${cursor}`);
      }
      chunks.slice(cursor, end + 1).forEach((chunk) => events.push(chunk));
      cursor = end + 1;
    },
    /** Push what is left and close the stream. */
    rest() {
      chunks.slice(cursor).forEach((chunk) => events.push(chunk));
      events.end();
    },
  };
}

const activity = () => screen.getByTestId("assistant-activity");

describe("the activity line", () => {
  it("says what the assistant is doing, from the last step's parts, until its answer starts", async () => {
    const user = userEvent.setup();
    const events = controllableRunEvents();
    const feed = scriptFeeder(nativeWebFetchRun(), events);
    server.use(mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, events.resolver));
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    await user.type(
      await screen.findByRole("textbox", { name: "Message" }),
      "What changed in Python 3.14?"
    );
    await user.keyboard("{Enter}");
    // Before the first chunk the thread shows its own placeholder; the message does not exist yet.
    expect(await screen.findByText("Thinking…")).toBeInTheDocument();
    expect(screen.queryByTestId("assistant-activity")).toBeNull();

    // `start` creates the message: its activity line takes over from the thread's placeholder.
    feed.through("start-step");
    await waitFor(() => expect(activity()).toHaveTextContent("Working…"));
    expect(screen.queryByText("Thinking…")).toBeNull();

    // The built-in search: running, then landed with no text yet.
    feed.through("tool-input-available");
    await waitFor(() => expect(activity()).toHaveTextContent("Searching the web…"));
    feed.through("tool-output-available");
    await waitFor(() => expect(activity()).toHaveTextContent(`Searched for “${WEB_SEARCH_QUERY}”`));

    // The built-in fetch of the page it found.
    feed.through("tool-input-available");
    await waitFor(() => expect(activity()).toHaveTextContent("Reading docs.python.org…"));
    feed.through("tool-output-available");
    await waitFor(() => expect(activity()).toHaveTextContent("Read docs.python.org"));

    // The answer starts: the line goes away and stays away.
    feed.through("text-start");
    await waitFor(() => expect(screen.queryByTestId("assistant-activity")).toBeNull());
    feed.rest();
    expect(await screen.findByRole("link", { name: "[1]" })).toBeInTheDocument();
    expect(screen.queryByTestId("assistant-activity")).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument());
  });
});
