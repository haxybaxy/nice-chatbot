import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { makeRun } from "@/test/msw/fixtures/chat";
import { CONVERSATION_ID } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { controllableRunEvents, mockRunEvents } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

const THREAD_ROUTE = `/app/teams/team-1/chat/${CONVERSATION_ID}`;

describe("stopping a response", () => {
  it("aborts the stream, cancels the run on the backend and keeps the partial answer", async () => {
    const user = userEvent.setup();
    const events = controllableRunEvents();
    const cancelled: string[] = [];
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, ({ params }) =>
        HttpResponse.json(
          makeRun({ id: "run-stop", conversationId: params.conversation_id, status: "running" }),
          { status: 201 }
        )
      ),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, events.resolver),
      mockApi.post(API_ENDPOINTS.CHAT.CANCEL_RUN, ({ params }) => {
        cancelled.push(`${params.conversation_id}/${params.run_id}`);
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    await user.type(await screen.findByRole("textbox", { name: "Message" }), "Write an essay");
    await user.keyboard("{Enter}");
    events.push({ type: "start", messageId: "msg-a1" });
    events.push({ type: "text-start", id: "t1" });
    events.push({ type: "text-delta", id: "t1", delta: "Once upon a time" });
    expect(await screen.findByText("Once upon a time")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Stop" }));

    await expect(events.aborted).resolves.toBeUndefined();
    await waitFor(() => expect(cancelled).toEqual([`${CONVERSATION_ID}/run-stop`]));
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument());
    expect(screen.getByText("Once upon a time")).toBeInTheDocument();
  });

  it("treats an already-finished run as stopped", async () => {
    const user = userEvent.setup();
    const events = controllableRunEvents();
    server.use(
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, events.resolver),
      mockApi.post(API_ENDPOINTS.CHAT.CANCEL_RUN, () =>
        HttpResponse.json(
          {
            error: "Run already finished",
            code: "CONFLICT",
            statusCode: 409,
            correlationId: "c-1",
          },
          { status: 409 }
        )
      )
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    await user.type(await screen.findByRole("textbox", { name: "Message" }), "Go");
    await user.keyboard("{Enter}");
    events.push({ type: "start", messageId: "msg-a1" });
    await screen.findByRole("button", { name: "Stop" });

    await user.click(screen.getByRole("button", { name: "Stop" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument());
    expect(screen.queryByText("Run already finished")).toBeNull();
  });
});
