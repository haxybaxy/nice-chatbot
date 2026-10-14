import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import type { CreateMessageRequest } from "@/features/chat/types";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { makeRun } from "@/test/msw/fixtures/chat";
import { RESEARCH_PLAN, researchRun, SOURCE } from "@/test/msw/fixtures/run-chunks";
import { CONVERSATION_ID } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { controllableRunEvents, mockRunEvents } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

const THREAD_ROUTE = `/app/teams/team-1/chat/${CONVERSATION_ID}`;

describe("deep research", () => {
  it("sends the mode, then renders the plan, the tasks reconciled by id, the report and the citation check", async () => {
    const user = userEvent.setup();
    const bodies: CreateMessageRequest[] = [];
    const events = controllableRunEvents();
    const chunks = researchRun();
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request, params }) => {
        bodies.push(await request.json());
        return HttpResponse.json(
          makeRun({ id: "run-1", conversationId: params.conversation_id, mode: "deep_research" }),
          { status: 201 }
        );
      }),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, events.resolver)
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    await user.click(await screen.findByRole("button", { name: "Deep research" }));
    // The chat-only toggles leave with the mode.
    expect(screen.queryByRole("button", { name: "Search" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Code" })).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Compare A and B");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]?.mode).toBe("deep_research");

    // start, start-step, plan
    chunks.slice(0, 3).forEach((chunk) => events.push(chunk));
    const panel = await screen.findByTestId("deep-research");
    expect(within(panel).getByText(RESEARCH_PLAN.summary)).toBeInTheDocument();
    expect(within(panel).getByText("0 of 2 tasks complete")).toBeInTheDocument();
    expect(within(panel).getByText("medium")).toBeInTheDocument();

    // t1 running → its row shows the last action
    events.push(chunks[3]!);
    expect(await within(panel).findByText("Searching benchmarks")).toBeInTheDocument();
    expect(panel.querySelector('[data-task="t1"]')).toHaveAttribute("data-task-status", "running");

    // t1 done → replaced in place (still one row), t2 done
    events.push(chunks[4]!);
    events.push(chunks[5]!);
    expect(await within(panel).findByText("2 of 2 tasks complete")).toBeInTheDocument();
    expect(panel.querySelectorAll('[data-task="t1"]')).toHaveLength(1);
    expect(within(panel).getByText("A is cheaper.")).toBeInTheDocument();
    expect(within(panel).getByText("B is faster.")).toBeInTheDocument();

    // the source, the report and the citation check
    chunks.slice(6).forEach((chunk) => events.push(chunk));
    events.end();
    expect(await screen.findByRole("heading", { name: "Findings" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "[1]" })).toHaveAttribute("href", SOURCE.url);
    expect(await within(panel).findByText("1 unsupported citation")).toBeInTheDocument();
    expect(within(panel).getByText("1 unknown citation number")).toBeInTheDocument();
    expect(screen.getAllByTestId("message-assistant")).toHaveLength(2);
  });
});
