import {
  type DefaultBodyType,
  http,
  HttpResponse,
  type HttpHandler,
  type HttpResponseResolver,
} from "msw";

import { API_ENDPOINTS } from "@/shared/config/api-endpoints";

import { ATTACHMENT_BYTES, attachmentKind, makeAttachment } from "../fixtures/chat";
import { errorResponse } from "../fixtures/error";
import { mockApi, url } from "../typed-http";

/**
 * The content route answers bytes, not the operation's JSON `*Out` (its 200 is
 * `application/octet-stream`), so like the event stream it registers through a raw `http.get`
 * — `mockApi.get` would type the response as JSON. The contract validator skips it for the same
 * reason. `attachmentContentResponse` builds the response the backend sends: the stored media
 * type, an inline RFC 5987 disposition and the private cache header.
 */
export function mockAttachmentContent(resolver: HttpResponseResolver): HttpHandler {
  return http.get(url(API_ENDPOINTS.ATTACHMENTS.CONTENT), resolver);
}

export function attachmentContentResponse(
  bytes: Uint8Array,
  mediaType: string,
  filename = "photo.png"
): HttpResponse<DefaultBodyType> {
  return new HttpResponse(bytes, {
    headers: {
      "content-type": mediaType,
      "content-disposition": `inline; filename*=UTF-8''${encodeURIComponent(filename)}`,
      "cache-control": "private, max-age=3600",
    },
  });
}

/**
 * The multipart `file` field, or `undefined`. Structural on purpose: undici parses the body into
 * its own `File` class, so `instanceof File` (jsdom's global) is false in a handler; a
 * `FormDataEntryValue` that is not a string is a `File` by type.
 */
export function uploadedFile(form: FormData): File | undefined {
  const file = form.get("file");
  return typeof file === "string" || file === null ? undefined : file;
}

/**
 * Resting-state attachment handlers: an upload becomes an `AttachmentOut` built from the
 * multipart `file` field (its name, type and size), every id reads back as a small PNG, and a
 * delete succeeds. Override per test for a refused upload, a document's metadata or a 404.
 */
export const attachmentHandlers = [
  mockApi.post(API_ENDPOINTS.ATTACHMENTS.UPLOAD, async ({ request, params }) => {
    const file = uploadedFile(await request.formData());
    if (!file) {
      return errorResponse(422, "VALIDATION_ERROR", "A `file` field is required");
    }
    return HttpResponse.json(
      makeAttachment({
        teamId: params.team_id,
        filename: file.name,
        mediaType: file.type,
        sizeBytes: file.size,
        kind: attachmentKind(file.type),
      }),
      { status: 201 }
    );
  }),

  mockApi.get(API_ENDPOINTS.ATTACHMENTS.ATTACHMENT, ({ params }) =>
    HttpResponse.json(makeAttachment({ id: params.attachment_id }))
  ),

  mockAttachmentContent(() => attachmentContentResponse(ATTACHMENT_BYTES, "image/png")),

  mockApi.delete(
    API_ENDPOINTS.ATTACHMENTS.ATTACHMENT,
    () => new HttpResponse(null, { status: 204 })
  ),
];
