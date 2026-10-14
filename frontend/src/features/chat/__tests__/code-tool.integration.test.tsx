import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import type { CreateMessageRequest } from "@/features/chat/types";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { makeRun } from "@/test/msw/fixtures/chat";
import { CODE_SNIPPET, codeErrorRun, codeRun } from "@/test/msw/fixtures/run-chunks";
import { CONVERSATION_ID } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { controllableRunEvents, mockRunEvents, runEventsResponse } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

const THREAD_ROUTE = `/app/teams/team-1/chat/${CONVERSATION_ID}`;

async function sendWithCode(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.click(await screen.findByRole("button", { name: "Code" }));
  await user.type(screen.getByRole("textbox", { name: "Message" }), text);
  await user.keyboard("{Enter}");
}

describe("the code tool", () => {
  it("shows the program while it runs, then the terminal with the exit badge", async () => {
    const user = userEvent.setup();
    const bodies: CreateMessageRequest[] = [];
    const events = controllableRunEvents();
    const chunks = codeRun();
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request, params }) => {
        bodies.push(await request.json());
        return HttpResponse.json(makeRun({ id: "run-1", conversationId: params.conversation_id }), {
          status: 201,
        });
      }),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, events.resolver)
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });
    await sendWithCode(user, "What is 17*23? Use code.");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]?.tools).toEqual({ webSearch: false, code: true });

    // start, start-step, tool-input-start, tool-input-available → running
    chunks.slice(0, 4).forEach((chunk) => events.push(chunk));
    expect(await screen.findByText("Running python")).toBeInTheDocument();
    expect(screen.getByText("Running…")).toBeInTheDocument();
    expect(screen.getByText(CODE_SNIPPET)).toBeInTheDocument();

    // tool-output-available → the terminal
    chunks.slice(4).forEach((chunk) => events.push(chunk));
    events.end();
    expect(await screen.findByText("exit 0")).toBeInTheDocument();
    expect(screen.getByText("exit 0")).toHaveAttribute("data-variant", "secondary");
    expect(screen.getByText("42 ms")).toBeInTheDocument();
    expect(screen.getByText("Ran python")).toBeInTheDocument();
    expect(within(screen.getByTestId("code-terminal")).getByText(/391/)).toBeInTheDocument();
    expect(await screen.findByText("The answer is 391.")).toBeInTheDocument();
  });

  it("marks a non-zero exit as a failure and shows stderr", async () => {
    const user = userEvent.setup();
    server.use(
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () =>
        runEventsResponse(codeRun({ exitCode: 1 }))
      )
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });
    await sendWithCode(user, "Break it");

    expect(await screen.findByText("exit 1")).toHaveAttribute("data-variant", "destructive");
    expect(
      within(screen.getByTestId("code-terminal")).getByText(/Traceback: boom/)
    ).toBeInTheDocument();
  });

  it("shows the tool's error when it could not run", async () => {
    const user = userEvent.setup();
    server.use(
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () => runEventsResponse(codeErrorRun()))
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });
    await sendWithCode(user, "echo");

    expect(await screen.findByText("Sandbox unavailable")).toBeInTheDocument();
    expect(screen.getByText("Ran bash")).toBeInTheDocument();
    expect(screen.getByText("echo hi")).toBeInTheDocument();
  });
});
