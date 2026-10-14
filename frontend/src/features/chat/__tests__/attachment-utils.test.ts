import { describe, expect, it } from "vitest";

import type { ChatMessagePart } from "@/features/chat/types";
import {
  ATTACHMENT_ACCEPT,
  attachmentIdFromUrl,
  formatBytes,
  isAcceptedFile,
  toFileUIPart,
} from "@/features/chat/utils/attachments";
import { toMessagePartsIn } from "@/features/chat/utils/message-parts";
import { makeAttachment } from "@/test/msw/fixtures/chat";

const file = (filename: string, url: string): ChatMessagePart => ({
  type: "file",
  mediaType: "application/pdf",
  filename,
  url,
});

describe("toMessagePartsIn", () => {
  it("keeps text parts and sends a file part as the id its url points at — nothing else", () => {
    expect(
      toMessagePartsIn([
        file("a.pdf", "/api/attachments/att-1/content"),
        file("b.pdf", "http://localhost:8000/api/attachments/att-2/content?download=true"),
        { type: "text", text: "Compare these" },
      ])
    ).toEqual([
      { type: "file", attachmentId: "att-1" },
      { type: "file", attachmentId: "att-2" },
      { type: "text", text: "Compare these" },
    ]);
  });

  it("accepts files alone and text alone, and ignores parts that are neither", () => {
    expect(toMessagePartsIn([file("a.pdf", "/api/attachments/att-1/content")])).toEqual([
      { type: "file", attachmentId: "att-1" },
    ]);
    expect(toMessagePartsIn([{ type: "step-start" }, { type: "text", text: "hi" }])).toEqual([
      { type: "text", text: "hi" },
    ]);
  });

  it("refuses an empty message and a file that is not an upload", () => {
    expect(() => toMessagePartsIn([{ type: "text", text: "  " }])).toThrow(
      /no text and no attachment/
    );
    expect(() => toMessagePartsIn([])).toThrow(/no text and no attachment/);
    expect(() => toMessagePartsIn([file("x.pdf", "blob:mock/1")])).toThrow(
      '"x.pdf" is not an uploaded attachment.'
    );
  });
});

describe("attachmentIdFromUrl", () => {
  it("reads the id of a content url, relative or absolute, with or without a query", () => {
    expect(attachmentIdFromUrl("/api/attachments/att-1/content")).toBe("att-1");
    expect(attachmentIdFromUrl("https://api.example.com/api/attachments/att-1/content")).toBe(
      "att-1"
    );
    expect(attachmentIdFromUrl("/api/attachments/att-1/content?download=true")).toBe("att-1");
    expect(attachmentIdFromUrl("/api/attachments/a%20b/content")).toBe("a b");
  });

  it("is undefined for anything else", () => {
    expect(attachmentIdFromUrl("/api/attachments/att-1")).toBeUndefined();
    expect(attachmentIdFromUrl("data:image/png;base64,AAAA")).toBeUndefined();
    expect(attachmentIdFromUrl("blob:http://localhost/att-1/content")).toBeUndefined();
    expect(attachmentIdFromUrl("/api/attachments//content")).toBeUndefined();
  });
});

describe("toFileUIPart", () => {
  it("is the SDK file part the backend persists (the id travels inside url)", () => {
    const attachment = makeAttachment({
      id: "att-7",
      filename: "notes.md",
      mediaType: "text/markdown",
    });
    const part = toFileUIPart(attachment);
    expect(part).toEqual({
      type: "file",
      mediaType: "text/markdown",
      filename: "notes.md",
      url: "/api/attachments/att-7/content",
    });
    expect(toMessagePartsIn([part])).toEqual([{ type: "file", attachmentId: "att-7" }]);
  });
});

describe("isAcceptedFile", () => {
  const make = (name: string, type: string) => new File(["x"], name, { type });

  it("accepts images, pdf, docx, text and the code extensions the OS leaves untyped", () => {
    expect(isAcceptedFile(make("a.png", "image/png"))).toBe(true);
    expect(isAcceptedFile(make("a.pdf", "application/pdf"))).toBe(true);
    expect(
      isAcceptedFile(
        make("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
      )
    ).toBe(true);
    expect(isAcceptedFile(make("a.csv", "text/csv"))).toBe(true);
    expect(isAcceptedFile(make("main.py", ""))).toBe(true);
    expect(isAcceptedFile(make("main.ts", "video/mp2t"))).toBe(true);
    expect(isAcceptedFile(make("schema.sql", ""))).toBe(true);
  });

  it("refuses what the backend would", () => {
    expect(isAcceptedFile(make("setup.exe", "application/x-msdownload"))).toBe(false);
    expect(isAcceptedFile(make("clip.mp4", "video/mp4"))).toBe(false);
    expect(isAcceptedFile(make("archive.zip", "application/zip"))).toBe(false);
    expect(isAcceptedFile(make("photo.bmp", "image/bmp"))).toBe(false);
  });

  it("builds the picker's accept list from the same allowlists", () => {
    expect(ATTACHMENT_ACCEPT).toContain("image/png");
    expect(ATTACHMENT_ACCEPT).toContain("application/pdf");
    expect(ATTACHMENT_ACCEPT).toContain("text/*");
    expect(ATTACHMENT_ACCEPT).toContain(".py");
  });
});

describe("formatBytes", () => {
  it("picks the unit and rounds like a file manager", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(999)).toBe("999 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(10 * 1024 * 1024)).toBe("10 MB");
    expect(formatBytes(1.5 * 1024 * 1024 * 1024)).toBe("1.5 GB");
  });
});
