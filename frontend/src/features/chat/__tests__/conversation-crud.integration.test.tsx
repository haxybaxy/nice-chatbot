import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import type { UpdateConversationRequest } from "@/features/chat/types";
import { AppToaster } from "@/providers/toaster";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { makeConversation } from "@/test/msw/fixtures/chat";
import { errorResponse } from "@/test/msw/fixtures/error";
import { CONVERSATION_ID } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

const THREAD_ROUTE = `/app/teams/team-1/chat/${CONVERSATION_ID}`;
const HOUR = 60 * 60 * 1000;

describe("the conversation list", () => {
  it("groups by day and loads the next page with the cursor", async () => {
    const user = userEvent.setup();
    const now = Date.now();
    const cursors: (string | null)[] = [];
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATIONS, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        cursors.push(cursor);
        return HttpResponse.json(
          cursor === null
            ? {
                items: [
                  makeConversation({
                    id: "c-today",
                    title: "Today's chat",
                    lastMessageAt: new Date(now).toISOString(),
                  }),
                  makeConversation({
                    id: "c-yesterday",
                    title: "Yesterday's chat",
                    lastMessageAt: new Date(now - 24 * HOUR).toISOString(),
                  }),
                ],
                nextCursor: "page-2",
              }
            : {
                items: [
                  makeConversation({
                    id: "c-old",
                    title: "Last week's chat",
                    lastMessageAt: new Date(now - 7 * 24 * HOUR).toISOString(),
                  }),
                ],
              }
        );
      })
    );
    renderWithProviders(<App />, { route: "/app/teams/team-1/chat" });

    expect(await screen.findByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Yesterday")).toBeInTheDocument();
    expect(screen.queryByText("Earlier")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Earlier")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Last week's chat/ })).toBeInTheDocument();
    expect(cursors).toEqual([null, "page-2"]);
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("renames through the dialog with exactly the title field", async () => {
    const user = userEvent.setup();
    const bodies: UpdateConversationRequest[] = [];
    let title = "Hello there";
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATIONS, ({ params }) =>
        HttpResponse.json({
          items: [makeConversation({ id: CONVERSATION_ID, teamId: params.team_id, title })],
        })
      ),
      mockApi.patch(API_ENDPOINTS.CHAT.CONVERSATION, async ({ request, params }) => {
        const body = await request.json();
        bodies.push(body);
        title = body.title ?? title;
        return HttpResponse.json(makeConversation({ id: params.conversation_id, title }));
      })
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    await user.click(await screen.findByRole("button", { name: "Actions for Hello there" }));
    await user.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const dialog = await screen.findByRole("dialog", { name: "Rename conversation" });
    const input = within(dialog).getByLabelText("Title");
    expect(input).toHaveValue("Hello there");
    await user.clear(input);
    await user.type(input, "Renamed");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(bodies).toEqual([{ title: "Renamed" }]);
    expect(await screen.findByRole("link", { name: /Renamed/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Renamed" })).toBeInTheDocument();
  });

  it("deletes the open conversation and returns to a new chat", async () => {
    const user = userEvent.setup();
    const deleted: string[] = [];
    server.use(
      mockApi.delete(API_ENDPOINTS.CHAT.CONVERSATION, ({ params }) => {
        deleted.push(params.conversation_id);
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    await user.click(await screen.findByRole("button", { name: "Actions for Hello there" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("heading", { name: "New chat" })).toBeInTheDocument();
    expect(deleted).toEqual([CONVERSATION_ID]);
  });

  it("explains a 409 on delete while a response is running", async () => {
    const user = userEvent.setup();
    server.use(
      mockApi.delete(API_ENDPOINTS.CHAT.CONVERSATION, () =>
        errorResponse(409, "CONFLICT", "A run is active")
      )
    );
    renderWithProviders(
      <>
        <App />
        <AppToaster />
      </>,
      { route: THREAD_ROUTE }
    );

    await user.click(await screen.findByRole("button", { name: "Actions for Hello there" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" })
    );

    expect(
      await screen.findByText("Stop the response before deleting this conversation.")
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Hello there" })).toBeInTheDocument();
  });

  it("shows a not-found state for a conversation that does not exist", async () => {
    renderWithProviders(<App />, { route: "/app/teams/team-1/chat/conv-missing" });

    expect(
      await screen.findByText("This conversation does not exist or is not visible to you.")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a new chat" })).toHaveAttribute(
      "href",
      "/app/teams/team-1/chat"
    );
  });
});
