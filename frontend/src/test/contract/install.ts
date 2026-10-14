/**
 * Global contract enforcement for the test suite.
 *
 * Why lifecycle listeners and not an `http.all("*")` validator: MSW gives
 * runtime `server.use()` handlers precedence over initial handlers, and most
 * integration tests override handlers via `server.use()` — an override would
 * answer before a fall-through validator ran. `request:start` / `response:mocked`
 * fire for EVERY request/response regardless of handler precedence, so validation
 * can't be bypassed.
 *
 * Two directions:
 *  - `request:start` → validate the outgoing body + query params (would the
 *    backend 422 this request?). Fix the service/component.
 *  - `response:mocked` → validate the mocked 2xx response against the backend's
 *    `*Out` schema (is the mock a shape the backend could actually return?). Fix
 *    the MSW handler/fixture. This is what makes the boundary tests trustworthy.
 *
 * Flow: record any violation as requests/responses fly, then fail the test in
 * `afterEach` via `assertNoContractViolations()` (wired in `src/test/setup.ts`).
 */
import type { SetupServer } from "msw/node";

import {
  validateRequest,
  validateQueryParams,
  validateResponse,
  formatViolation,
  type ContractViolation,
} from "./validate-request";

let installed = false;
let suppressed = false;
const pending: Promise<void>[] = [];
const violations: ContractViolation[] = [];

export function installContractValidation(server: SetupServer): void {
  if (installed) return; // idempotent across a file's beforeAll
  installed = true;

  server.events.on("request:start", ({ request }) => {
    const method = request.method.toUpperCase();
    const { pathname, searchParams } = new URL(request.url);

    // Query params ride on every method and need no body read, so they're checked
    // first and synchronously — unlike bodies, which are POST/PUT/PATCH only.
    if (!suppressed) {
      const queryViolation = validateQueryParams(method, pathname, searchParams);
      if (queryViolation) violations.push(queryViolation);
    }

    if (method !== "POST" && method !== "PUT" && method !== "PATCH") return;

    // Body read is async; park the promise so afterEach can await it before asserting.
    const task = request
      .clone()
      .json()
      .then((body: unknown) => {
        if (suppressed) return;
        const violation = validateRequest(method, pathname, body);
        if (violation) violations.push(violation);
      })
      .catch(() => {
        // Empty / non-JSON body — nothing to contract-check here.
      });
    pending.push(task);
  });

  server.events.on("response:mocked", ({ request, response }) => {
    // Only 2xx JSON responses carry a schema worth checking; deliberate error
    // mocks (4xx/5xx) and empty bodies (204) are skipped.
    if (response.status < 200 || response.status >= 300) return;
    if (!(response.headers.get("content-type") ?? "").includes("application/json")) return;
    const method = request.method.toUpperCase();
    const { pathname } = new URL(request.url);

    const task = response
      .clone()
      .json()
      .then((body: unknown) => {
        if (suppressed) return;
        const violation = validateResponse(method, pathname, response.status, body);
        if (violation) violations.push(violation);
      })
      .catch(() => {
        // Non-JSON body despite the header — nothing to validate.
      });
    pending.push(task);
  });
}

/**
 * Opt the current test out of enforcement (e.g. deliberately testing a 4xx). There are zero
 * uses today — keep it that way; see CLAUDE.md.
 * @public
 */
export function allowContractViolations(): void {
  suppressed = true;
}

/**
 * Await in-flight validations and throw if any request would have been rejected
 * by the backend. Always clears state so a violation can't bleed into the next
 * test. Call from a global `afterEach`.
 */
export async function assertNoContractViolations(): Promise<void> {
  try {
    await Promise.all(pending);
    if (violations.length > 0) {
      const detail = violations.map(formatViolation).join("\n");
      const kinds = new Set(violations.map((v) => v.kind));
      const notes = [
        kinds.has("body") ? 'a request body field the backend rejects (extra="forbid")' : null,
        kinds.has("query") ? "an undeclared query parameter" : null,
        kinds.has("response")
          ? "a mocked response that doesn't match the backend `*Out` schema"
          : null,
      ].filter(Boolean);
      const hasRequest = kinds.has("body") || kinds.has("query");
      const fix =
        hasRequest && kinds.has("response")
          ? "Fix the service/component (requests) or the MSW handler/fixture (responses) — never the snapshot."
          : kinds.has("response")
            ? "Fix the MSW handler/fixture to match the backend response shape — not the snapshot."
            : "Fix the service/component that builds the request — not the mock.";
      throw new Error(`Contract violation(s): ${notes.join("; ")}.\n${fix}\n${detail}`);
    }
  } finally {
    pending.length = 0;
    violations.length = 0;
    suppressed = false;
  }
}
