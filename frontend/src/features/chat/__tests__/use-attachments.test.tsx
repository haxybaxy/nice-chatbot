import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  useAttachmentObjectUrl,
  useDeleteAttachment,
  useDownloadAttachment,
} from "@/features/chat/hooks/use-attachments";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";
import { QUERY_KEYS } from "@/shared/constants/query-keys";
import { tokenStorage } from "@/shared/services/token-storage";
import { ATTACHMENT_BYTES } from "@/test/msw/fixtures/chat";
import { errorResponse } from "@/test/msw/fixtures/error";
import { makeTokens } from "@/test/msw/fixtures/user";
import { attachmentContentResponse, mockAttachmentContent } from "@/test/msw/handlers/attachments";
import { server } from "@/test/msw/server";
import { mockApi } from "@/test/msw/typed-http";

const ATTACHMENT_ID = "att-hook";

function setup() {
  tokenStorage.setTokens(makeTokens());
  // `gcTime: 0`: a query is dropped as soon as its last observer unmounts, which is when the
  // object URL must be revoked.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

const createObjectURL = () => vi.mocked(URL.createObjectURL);
const revokeObjectURL = () => vi.mocked(URL.revokeObjectURL);

describe("useAttachmentObjectUrl", () => {
  it("fetches the bytes once, hands out an object URL and revokes it when the query is dropped", async () => {
    let requests = 0;
    server.use(
      mockAttachmentContent(() => {
        requests += 1;
        return attachmentContentResponse(ATTACHMENT_BYTES, "image/png");
      })
    );
    const { wrapper } = setup();

    const first = renderHook(() => useAttachmentObjectUrl(ATTACHMENT_ID), { wrapper });
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
    const url = first.result.current.data;
    expect(url).toMatch(/^blob:mock\//);
    expect(createObjectURL()).toHaveBeenCalledTimes(1);
    const [blob] = createObjectURL().mock.calls[0] ?? [];
    if (!(blob instanceof Blob)) {
      throw new Error("createObjectURL was not given a Blob");
    }
    expect(blob.type).toBe("image/png");
    expect(blob.size).toBe(ATTACHMENT_BYTES.byteLength);

    // A second reader of the same attachment shares the query: no second request, same URL.
    const second = renderHook(() => useAttachmentObjectUrl(ATTACHMENT_ID), { wrapper });
    await waitFor(() => expect(second.result.current.data).toBe(url));
    expect(requests).toBe(1);

    // Still one observer: nothing revoked. None: the cache drops the query and the URL goes.
    first.unmount();
    expect(revokeObjectURL()).not.toHaveBeenCalled();
    second.unmount();
    await waitFor(() => expect(revokeObjectURL()).toHaveBeenCalledWith(url));
    expect(revokeObjectURL()).toHaveBeenCalledTimes(1);
  });

  it("surfaces a 404 as the query's error, with the status to branch on", async () => {
    server.use(
      mockAttachmentContent(() => errorResponse(404, "NOT_FOUND", "Attachment not found"))
    );
    const { wrapper } = setup();

    const { result } = renderHook(() => useAttachmentObjectUrl(ATTACHMENT_ID), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ status: 404, message: "Attachment not found" });
    expect(createObjectURL()).not.toHaveBeenCalled();
  });
});

describe("useDownloadAttachment", () => {
  const clicks: { href: string; download: string }[] = [];
  afterEach(() => {
    clicks.length = 0;
    vi.restoreAllMocks();
  });

  it("saves the bytes under the filename through an anchor click, reusing a cached URL", async () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement
    ) {
      clicks.push({ href: this.href, download: this.download });
    });
    let requests = 0;
    server.use(
      mockAttachmentContent(() => {
        requests += 1;
        return attachmentContentResponse(ATTACHMENT_BYTES, "application/pdf", "report.pdf");
      })
    );
    const { wrapper } = setup();
    const shown = renderHook(() => useAttachmentObjectUrl(ATTACHMENT_ID), { wrapper });
    await waitFor(() => expect(shown.result.current.isSuccess).toBe(true));
    const { result } = renderHook(() => useDownloadAttachment(), { wrapper });

    await act(() =>
      result.current.mutateAsync({ attachmentId: ATTACHMENT_ID, filename: "report.pdf" })
    );

    expect(clicks).toEqual([{ href: shown.result.current.data, download: "report.pdf" }]);
    expect(requests).toBe(1);
    expect(document.querySelector("a[download]")).toBeNull();
  });
});

describe("useDeleteAttachment", () => {
  it("deletes the upload and drops its cached URL", async () => {
    const deleted: string[] = [];
    server.use(
      mockApi.delete(API_ENDPOINTS.ATTACHMENTS.ATTACHMENT, ({ params }) => {
        deleted.push(params.attachment_id);
        return new HttpResponse(null, { status: 204 });
      })
    );
    const { wrapper, queryClient } = setup();
    const shown = renderHook(() => useAttachmentObjectUrl(ATTACHMENT_ID), { wrapper });
    await waitFor(() => expect(shown.result.current.isSuccess).toBe(true));
    const url = shown.result.current.data;
    const { result } = renderHook(() => useDeleteAttachment(), { wrapper });

    await act(() => result.current.mutateAsync(ATTACHMENT_ID));

    expect(deleted).toEqual([ATTACHMENT_ID]);
    expect(queryClient.getQueryData(QUERY_KEYS.chat.attachment(ATTACHMENT_ID))).toBeUndefined();
    expect(revokeObjectURL()).toHaveBeenCalledWith(url);
  });
});
