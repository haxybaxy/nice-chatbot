import {
  type QueryClient,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { QUERY_KEYS } from "@/shared/constants/query-keys";

import { chatService } from "../services/chat.service";
import type { Attachment } from "../types";
import { downloadObjectUrl } from "../utils/attachments";

/** One file of a multi-file upload: the attachment it became, or the error that refused it. */
export type UploadOutcome =
  | { file: File; attachment: Attachment; error?: undefined }
  | { file: File; attachment?: undefined; error: Error };

/**
 * Upload several files for a team in parallel. The mutation itself resolves with one outcome
 * per file (a 400 on one file must not hide the others' success — the composer decides what to
 * do with a partial result); it rejects only when something outside the uploads threw.
 */
export function useUploadAttachments(teamId: string) {
  return useMutation({
    mutationFn: (files: readonly File[]) =>
      Promise.all(
        files.map(async (file): Promise<UploadOutcome> => {
          try {
            return { file, attachment: await chatService.uploadAttachment(teamId, file) };
          } catch (error) {
            return { file, error: error instanceof Error ? error : new Error(String(error)) };
          }
        })
      ),
  });
}

// ── Object URLs ──────────────────────────────────────────────────────────────
//
// An attachment's bytes are bearer-protected, so they are fetched through `apiClient.blob` and
// shown through an object URL. The URL lives exactly as long as its query: created in the
// `queryFn`, revoked when the query cache drops the query (after `gcTime` without observers,
// or when a sign-out / delete removes it). One cache subscription per QueryClient does the
// revoking — installed lazily by the first fetch, so `fetchQuery` callers are covered too. The
// query never goes stale (`staleTime: Infinity`; the content of an attachment is immutable), so
// a URL is not replaced behind an `<img>`; the `queryFn` still revokes a previous value
// defensively.

const revokeInstalled = new WeakSet<QueryClient>();

function isObjectUrlKey(queryKey: readonly unknown[]): boolean {
  const prefix = QUERY_KEYS.chat.attachments;
  return (
    queryKey.length === prefix.length + 1 &&
    prefix.every((segment, index) => queryKey[index] === segment)
  );
}

function installRevokeOnRemove(queryClient: QueryClient): void {
  if (revokeInstalled.has(queryClient)) {
    return;
  }
  revokeInstalled.add(queryClient);
  queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== "removed") {
      return;
    }
    const { queryKey, state } = event.query;
    if (isObjectUrlKey(queryKey) && typeof state.data === "string") {
      URL.revokeObjectURL(state.data);
    }
  });
}

/** The object-URL query of one attachment (shared by the hook and the download mutation). */
export function attachmentObjectUrlOptions(queryClient: QueryClient, attachmentId: string) {
  const queryKey = QUERY_KEYS.chat.attachment(attachmentId);
  return queryOptions({
    queryKey,
    queryFn: async ({ signal }) => {
      installRevokeOnRemove(queryClient);
      const blob = await chatService.getAttachmentBlob(attachmentId, { signal });
      const previous = queryClient.getQueryData(queryKey);
      if (typeof previous === "string") {
        URL.revokeObjectURL(previous);
      }
      return URL.createObjectURL(blob);
    },
    staleTime: Infinity,
  });
}

/** An object URL for the attachment's bytes — `data` goes straight into an `<img src>`. */
export function useAttachmentObjectUrl(attachmentId: string) {
  const queryClient = useQueryClient();
  return useQuery(attachmentObjectUrlOptions(queryClient, attachmentId));
}

/** The attachment's metadata (kind, size, extraction status); immutable once uploaded. */
export function useAttachment(attachmentId: string) {
  return useQuery({
    queryKey: QUERY_KEYS.chat.attachmentMeta(attachmentId),
    queryFn: () => chatService.getAttachment(attachmentId),
    staleTime: Infinity,
  });
}

/** Withdraw an upload no message carries yet; its cached URL and metadata go with it. */
export function useDeleteAttachment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (attachmentId: string) => chatService.deleteAttachment(attachmentId),
    onSuccess: (_, attachmentId) =>
      queryClient.removeQueries({ queryKey: QUERY_KEYS.chat.attachment(attachmentId) }),
  });
}

/**
 * Save an attachment under its filename: the bytes through the same object-URL query (cached
 * when a thumbnail already shows them), then an anchor click with `download`.
 */
export function useDownloadAttachment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ attachmentId, filename }: { attachmentId: string; filename: string }) => {
      const url = await queryClient.fetchQuery(
        attachmentObjectUrlOptions(queryClient, attachmentId)
      );
      downloadObjectUrl(url, filename);
    },
  });
}
