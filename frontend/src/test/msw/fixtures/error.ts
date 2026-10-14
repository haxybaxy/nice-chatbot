import { HttpResponse } from "msw";

import type { Schema } from "@/shared/api/types";

type ErrorEnvelope = Schema<"ErrorOut">;

/** The one error envelope (`ErrorOut`), as the backend's exception handlers build it. */
function makeErrorOut(
  overrides: Partial<ErrorEnvelope> & Pick<ErrorEnvelope, "statusCode" | "code">
): ErrorEnvelope {
  return { error: "Request failed", correlationId: "c-1", ...overrides };
}

/** An error response with a well-formed envelope; `code` is the generated `ErrorCode` union. */
export function errorResponse(
  statusCode: number,
  code: ErrorEnvelope["code"],
  error = "Request failed"
): HttpResponse<ErrorEnvelope> {
  return HttpResponse.json(makeErrorOut({ statusCode, code, error }), { status: statusCode });
}
