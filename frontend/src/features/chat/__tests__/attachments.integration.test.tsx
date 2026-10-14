import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import type { CreateConversationRequest, CreateMessageRequest } from "@/features/chat/types";
import { ATTACHMENT_MAX_BYTES } from "@/features/chat/utils/attachments";
import { AppToaster } from "@/providers/toaster";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import {
  ATTACHMENT_BYTES,
  attachmentKind,
  DEFAULT_MODEL_ID,
  filePart,
  makeAttachment,
  makeConversation,
  makeConversationDetail,
  makeMessage,
  makeModel,
  makeRun,
  textPart,
} from "@/test/msw/fixtures/chat";
import { errorResponse } from "@/test/msw/fixtures/error";
import { textRun } from "@/test/msw/fixtures/run-chunks";
import {
  attachmentContentResponse,
  mockAttachmentContent,
  uploadedFile,
} from "@/test/msw/handlers/attachments";
import { CONVERSATION_ID, NEW_CONVERSATION_ID } from "@/test/msw/handlers/chat";
import { server } from "@/test/msw/server";
import { mockRunEvents, runEventsResponse } from "@/test/msw/sse";
import { mockApi } from "@/test/msw/typed-http";
import { renderWithProviders } from "@/test/render-with-providers";

const THREAD_ROUTE = `/app/teams/team-1/chat/${CONVERSATION_ID}`;
const RUN_OPTIONS = {
  model: DEFAULT_MODEL_ID,
  mode: "chat",
  tools: { webSearch: false, code: false },
};

const png = () => new File([ATTACHMENT_BYTES], "photo.png", { type: "image/png" });
const pdf = () => new File(["%PDF-1.4"], "report.pdf", { type: "application/pdf" });

const IMAGE = makeAttachment({ id: "att-photo.png" });
const DOCUMENT = makeAttachment({
  id: "att-report.pdf",
  filename: "report.pdf",
  mediaType: "application/pdf",
  kind: "pdf",
  sizeBytes: 2048,
});

/** Uploads answer with an id derived from the filename; metadata and content follow the id. */
function mockAttachmentsByName(uploads: { name: string; type: string; size: number }[] = []) {
  server.use(
    mockApi.post(API_ENDPOINTS.ATTACHMENTS.UPLOAD, async ({ request, params }) => {
      const file = uploadedFile(await request.formData());
      if (!file) {
        return errorResponse(422, "VALIDATION_ERROR", "file is required");
      }
      uploads.push({ name: file.name, type: file.type, size: file.size });
      return HttpResponse.json(
        makeAttachment({
          id: `att-${file.name}`,
          teamId: params.team_id,
          filename: file.name,
          mediaType: file.type,
          sizeBytes: file.name === "report.pdf" ? 2048 : file.size,
          kind: attachmentKind(file.type),
        }),
        { status: 201 }
      );
    }),
    mockApi.get(API_ENDPOINTS.ATTACHMENTS.ATTACHMENT, ({ params }) =>
      HttpResponse.json(params.attachment_id === DOCUMENT.id ? DOCUMENT : IMAGE)
    ),
    mockAttachmentContent(({ params }) =>
      params["attachment_id"] === DOCUMENT.id
        ? attachmentContentResponse(
            new TextEncoder().encode("%PDF-1.4"),
            "application/pdf",
            "report.pdf"
          )
        : attachmentContentResponse(ATTACHMENT_BYTES, "image/png")
    )
  );
}

const fileInput = () => screen.getByLabelText("Files to attach");
const submitButton = () => screen.getByRole("button", { name: "Submit" });

describe("attachments in the composer", () => {
  it("uploads every file first, sends them as file parts and renders the message like a persisted one", async () => {
    const user = userEvent.setup();
    const uploads: { name: string; type: string; size: number }[] = [];
    const bodies: CreateMessageRequest[] = [];
    mockAttachmentsByName(uploads);
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request, params }) => {
        bodies.push(await request.json());
        return HttpResponse.json(makeRun({ id: "run-1", conversationId: params.conversation_id }), {
          status: 201,
        });
      })
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });
    await screen.findByText("Hello! How can I help?");

    await user.upload(fileInput(), [png(), pdf()]);
    // Pending: the image as a thumbnail of the file itself, the document as a chip with its size.
    const strip = screen.getByTestId("composer-attachments");
    expect(within(strip).getByRole("img", { name: "photo.png" })).toHaveAttribute(
      "src",
      expect.stringMatching(/^blob:mock\//)
    );
    expect(within(strip).getByText("report.pdf")).toBeInTheDocument();
    expect(within(strip).getByText("8 B")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Message" }), "What is in these?");
    await user.click(submitButton());

    expect(await screen.findByText("Hello from the assistant.")).toBeInTheDocument();
    expect(uploads).toEqual([
      { name: "photo.png", type: "image/png", size: ATTACHMENT_BYTES.byteLength },
      { name: "report.pdf", type: "application/pdf", size: 8 },
    ]);
    // Exactly `FilePartIn` per upload (the contract validator rejects any extra field), files first.
    expect(bodies).toEqual([
      {
        parts: [
          { type: "file", attachmentId: "att-photo.png" },
          { type: "file", attachmentId: "att-report.pdf" },
          { type: "text", text: "What is in these?" },
        ],
        ...RUN_OPTIONS,
      },
    ]);
    // The optimistic user message: the image fetched through its id and shown as an object
    // URL, the document as a chip with the size from its metadata and a download action.
    const sent = screen.getAllByTestId("message-user").at(-1)!;
    expect(await within(sent).findByRole("img", { name: "photo.png" })).toHaveAttribute(
      "src",
      expect.stringMatching(/^blob:mock\//)
    );
    expect(within(sent).getByText("report.pdf")).toBeInTheDocument();
    expect(await within(sent).findByText("2 KB")).toBeInTheDocument();
    expect(within(sent).getByRole("button", { name: "Download report.pdf" })).toBeInTheDocument();
    expect(within(sent).getByText("What is in these?")).toBeInTheDocument();
    // The composer let go of everything.
    expect(screen.queryByTestId("composer-attachments")).toBeNull();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
    await waitFor(() => expect(submitButton()).toBeDisabled());
  });

  it("keeps the text and the files, and says why, when an upload is refused", async () => {
    const user = userEvent.setup();
    const sent: CreateMessageRequest[] = [];
    server.use(
      mockApi.post(API_ENDPOINTS.ATTACHMENTS.UPLOAD, () =>
        errorResponse(400, "BAD_REQUEST", "Unsupported media type")
      ),
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(makeRun(), { status: 201 });
      })
    );
    renderWithProviders(
      <>
        <App />
        <AppToaster />
      </>,
      { route: THREAD_ROUTE }
    );
    await screen.findByText("Hello! How can I help?");

    await user.upload(fileInput(), png());
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Look at this");
    await user.click(submitButton());

    expect(await screen.findByText("photo.png: Unsupported media type")).toBeInTheDocument();
    expect(sent).toEqual([]);
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Look at this");
    expect(
      within(screen.getByTestId("composer-attachments")).getByRole("img", { name: "photo.png" })
    ).toBeInTheDocument();
    await waitFor(() => expect(submitButton()).toBeEnabled());
  });

  it("sends a message with files and no text", async () => {
    const user = userEvent.setup();
    const bodies: CreateMessageRequest[] = [];
    mockAttachmentsByName();
    server.use(
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(makeRun({ id: "run-1" }), { status: 201 });
      })
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });
    await screen.findByText("Hello! How can I help?");

    expect(submitButton()).toBeDisabled();
    await user.upload(fileInput(), pdf());
    await waitFor(() => expect(submitButton()).toBeEnabled());
    // Enter in the (empty) textarea submits once a file makes the message non-empty.
    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.keyboard("{Enter}");

    expect(await screen.findByText("Hello from the assistant.")).toBeInTheDocument();
    expect(bodies[0]?.parts).toEqual([{ type: "file", attachmentId: "att-report.pdf" }]);
  });

  it("warns that a non-vision model will not see an attached image, and still sends", async () => {
    const user = userEvent.setup();
    const bodies: CreateMessageRequest[] = [];
    mockAttachmentsByName();
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.MODELS, () =>
        HttpResponse.json([
          makeModel({ id: "openai:text-only", supportsVision: false, isDefault: true }),
        ])
      ),
      mockApi.post(API_ENDPOINTS.CHAT.MESSAGES, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(makeRun({ id: "run-1" }), { status: 201 });
      })
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });
    await screen.findByText("Hello! How can I help?");

    await user.upload(fileInput(), pdf());
    expect(screen.queryByRole("note")).toBeNull();
    await user.upload(fileInput(), png());
    expect(screen.getByRole("note")).toHaveTextContent(
      "This model can't view images; they will be described as attached."
    );
    await user.click(screen.getByRole("button", { name: "Remove photo.png" }));
    expect(screen.queryByRole("note")).toBeNull();
    await user.upload(fileInput(), png());
    await user.click(submitButton());

    expect(await screen.findByText("Hello from the assistant.")).toBeInTheDocument();
    expect(bodies[0]?.parts).toEqual([
      { type: "file", attachmentId: "att-report.pdf" },
      { type: "file", attachmentId: "att-photo.png" },
    ]);
    expect(bodies[0]?.model).toBe("openai:text-only");
  });

  it("takes dropped and pasted files, refuses what the backend would, and removes on Backspace", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <App />
        <AppToaster />
      </>,
      { route: THREAD_ROUTE }
    );
    const textarea = await screen.findByRole("textbox", { name: "Message" });
    const form = textarea.closest("form")!;

    fireEvent.drop(form, { dataTransfer: { files: [png()], types: ["Files"] } });
    fireEvent.paste(textarea, { clipboardData: { items: [{ kind: "file", getAsFile: pdf }] } });
    const strip = screen.getByTestId("composer-attachments");
    expect(within(strip).getByRole("img", { name: "photo.png" })).toBeInTheDocument();
    expect(within(strip).getByText("report.pdf")).toBeInTheDocument();

    const exe = new File(["MZ"], "setup.exe", { type: "application/x-msdownload" });
    const huge = new File(["x"], "huge.png", { type: "image/png" });
    Object.defineProperty(huge, "size", { value: ATTACHMENT_MAX_BYTES + 1 });
    fireEvent.drop(form, { dataTransfer: { files: [exe, huge], types: ["Files"] } });
    expect(
      await screen.findByText("setup.exe: this file type is not supported.")
    ).toBeInTheDocument();
    expect(await screen.findByText("huge.png: larger than 10 MB.")).toBeInTheDocument();
    expect(within(strip).getAllByRole("listitem")).toHaveLength(2);

    const many = Array.from(
      { length: 4 },
      (_, i) => new File(["a"], `n${i}.txt`, { type: "text/plain" })
    );
    await user.upload(fileInput(), many);
    expect(await screen.findByText("At most 5 files per message.")).toBeInTheDocument();
    expect(within(strip).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Attach files" })).toBeDisabled();

    // Backspace in an empty textarea removes the last file; the remove button any file.
    await user.click(textarea);
    await user.keyboard("{Backspace}");
    expect(within(strip).queryByText("n2.txt")).toBeNull();
    await user.click(within(strip).getByRole("button", { name: "Remove photo.png" }));
    expect(within(strip).queryByRole("img", { name: "photo.png" })).toBeNull();
    expect(vi.mocked(URL.revokeObjectURL)).toHaveBeenCalledWith(
      expect.stringMatching(/^blob:mock\//)
    );
    expect(within(strip).getAllByRole("listitem")).toHaveLength(3);
  });
});

describe("attachments in the thread", () => {
  const clicks: { href: string; download: string }[] = [];
  afterEach(() => {
    clicks.length = 0;
    vi.restoreAllMocks();
  });

  function mockPersistedThread() {
    mockAttachmentsByName();
    server.use(
      mockApi.get(API_ENDPOINTS.CHAT.CONVERSATION, () =>
        HttpResponse.json(
          makeConversationDetail({
            conversation: { id: CONVERSATION_ID },
            messages: [
              makeMessage({
                id: "msg-u1",
                role: "user",
                parts: [filePart(IMAGE), filePart(DOCUMENT), textPart("Here are two files")],
              }),
              makeMessage({ id: "msg-a0", role: "assistant", text: "Got them." }),
            ],
          })
        )
      )
    );
  }

  it("renders persisted file parts as a thumbnail that opens full size and a chip that downloads", async () => {
    const user = userEvent.setup();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement
    ) {
      clicks.push({ href: this.href, download: this.download });
    });
    mockPersistedThread();
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    const message = await screen.findByTestId("message-user");
    const thumbnail = await within(message).findByRole("img", { name: "photo.png" });
    expect(thumbnail).toHaveAttribute("src", expect.stringMatching(/^blob:mock\//));
    expect(within(message).getByText("report.pdf")).toBeInTheDocument();
    expect(await within(message).findByText("2 KB")).toBeInTheDocument();
    expect(within(message).getByText("Here are two files")).toBeInTheDocument();

    await user.click(within(message).getByRole("button", { name: "Open photo.png" }));
    const dialog = await screen.findByRole("dialog", { name: "photo.png" });
    expect(within(dialog).getByRole("img", { name: "photo.png" })).toHaveAttribute(
      "src",
      thumbnail.getAttribute("src")
    );
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.click(within(message).getByRole("button", { name: "Download report.pdf" }));
    await waitFor(() =>
      expect(clicks).toEqual([
        { href: expect.stringMatching(/^blob:mock\//), download: "report.pdf" },
      ])
    );
  });

  it("shows an attachment this member cannot fetch as unavailable", async () => {
    mockPersistedThread();
    server.use(
      mockApi.get(API_ENDPOINTS.ATTACHMENTS.ATTACHMENT, () =>
        errorResponse(404, "NOT_FOUND", "Attachment not found")
      ),
      mockAttachmentContent(() => errorResponse(403, "FORBIDDEN", "Not a member"))
    );
    renderWithProviders(<App />, { route: THREAD_ROUTE });

    const message = await screen.findByTestId("message-user");
    await waitFor(() => expect(within(message).getAllByText("Unavailable")).toHaveLength(2));
    expect(within(message).getByText("photo.png")).toBeInTheDocument();
    expect(within(message).getByText("report.pdf")).toBeInTheDocument();
    expect(within(message).queryByRole("img")).toBeNull();
    expect(within(message).queryByRole("button", { name: /Download/ })).toBeNull();
  });
});

describe("starting a conversation with a file", () => {
  it("uploads it, creates the conversation with the file part and shows it in the new thread", async () => {
    const user = userEvent.setup();
    const creates: CreateConversationRequest[] = [];
    const activeRun = makeRun({
      id: "run-new",
      conversationId: NEW_CONVERSATION_ID,
      status: "running",
    });
    mockAttachmentsByName();
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
                messages: [
                  makeMessage({
                    id: "msg-u1",
                    role: "user",
                    parts: [filePart(IMAGE), textPart("What is this?")],
                  }),
                ],
              })
            )
          : errorResponse(404, "NOT_FOUND")
      ),
      mockApi.get(API_ENDPOINTS.CHAT.ACTIVE_RUN, () => HttpResponse.json(activeRun)),
      mockRunEvents(API_ENDPOINTS.CHAT.RUN_EVENTS, () =>
        runEventsResponse(textRun({ content: "A photo of a cat." }))
      )
    );
    renderWithProviders(<App />, { route: "/app/teams/team-1/chat" });
    await screen.findByRole("heading", { name: "New chat" });

    await user.upload(fileInput(), png());
    await user.type(screen.getByRole("textbox", { name: "Message" }), "What is this?");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("A photo of a cat.")).toBeInTheDocument();
    expect(creates).toEqual([
      {
        message: {
          parts: [
            { type: "file", attachmentId: "att-photo.png" },
            { type: "text", text: "What is this?" },
          ],
          ...RUN_OPTIONS,
        },
      },
    ]);
    const message = screen.getByTestId("message-user");
    expect(await within(message).findByRole("img", { name: "photo.png" })).toHaveAttribute(
      "src",
      expect.stringMatching(/^blob:mock\//)
    );
    expect(within(message).getByText("What is this?")).toBeInTheDocument();
  });
});
