/**
 * Request-contract validator.
 *
 * Validates an outgoing request body against the backend's committed OpenAPI
 * snapshot (`./openapi.json`), mirroring FastAPI's behavior: every `*In` schema
 * inherits Pydantic `extra="forbid"`, which serializes to
 * `additionalProperties: false`. So an unknown field here fails exactly as it
 * would on the wire — which is the bug class that previously slipped through
 * (MSW handlers never validated bodies).
 *
 * Test-only. Loaded by `src/test/setup.ts` via `./install`. The spec is loaded
 * as a raw string (`?raw`) and parsed at runtime — not a typed JSON import — to
 * keep `tsc` off a 900KB literal type. It only reaches the test bundle.
 */
import type { AnySchema, ErrorObject, ValidateFunction } from "ajv";
import Ajv2020 from "ajv/dist/2020";

import openapiSpecRaw from "./openapi.json?raw";

interface MediaType {
  schema?: unknown;
}
interface Parameter {
  name?: string;
  in?: string;
}
interface Operation {
  requestBody?: { content?: Record<string, MediaType> };
  parameters?: Parameter[];
  responses?: Record<string, { content?: Record<string, MediaType> }>;
}
interface OpenApiSpec {
  openapi: string;
  paths: Record<string, Record<string, Operation>>;
}

interface ContractError {
  field: string;
  keyword: string;
  message: string;
}
export interface ContractViolation {
  /** Which part of the exchange failed — they carry different remediation. */
  kind: "body" | "query" | "response";
  method: string;
  path: string;
  errors: ContractError[];
}

/** Only mutating methods carry request bodies the backend validates. */
const ENFORCED_METHODS = new Set(["post", "put", "patch"]);
/** Query params, by contrast, ride on every method. */
const HTTP_METHODS = new Set(["get", "put", "post", "delete", "patch", "head", "options"]);
const JSON_CONTENT_TYPE = "application/json";

const rawSpec: unknown = JSON.parse(openapiSpecRaw);
const spec = rawSpec as OpenApiSpec;

// validateFormats:false — enforce STRUCTURE (unknown fields, required, types),
// not value formats. The prod breakage was extra="forbid", not bad uuid/email
// patterns; synthetic test fixtures legitimately use ids like "msg-1", and
// forcing them to be real UUIDs is churn with no real-bug payoff.
const ajv = new Ajv2020({ strict: false, allErrors: true, validateFormats: false });
if (!spec.openapi.startsWith("3.1")) {
  // FastAPI emits 3.1 (JSON Schema 2020-12). 3.0.x uses `nullable` etc. that
  // Ajv2020 won't honor — surface it loudly rather than silently mis-validate.
  console.warn(
    `[contract] openapi.json reports ${spec.openapi}; this validator targets 3.1.x. ` +
      `Regenerate against a 3.1 backend or add a 3.0 compatibility shim.`
  );
}
ajv.addSchema(rawSpec as AnySchema, "openapi");

/** JSON Pointer escaping per RFC 6901 (`~` -> `~0`, `/` -> `~1`). */
function escapePointer(segment: string): string {
  return segment.replace(/~/g, "~0").replace(/\//g, "~1");
}

function pointerFor(rawPath: string, method: string): string {
  return (
    `openapi#/paths/${escapePointer(rawPath)}/${method}` +
    `/requestBody/content/${escapePointer(JSON_CONTENT_TYPE)}/schema`
  );
}

function pointerForResponse(rawPath: string, method: string, status: string): string {
  return (
    `openapi#/paths/${escapePointer(rawPath)}/${method}` +
    `/responses/${escapePointer(status)}/content/${escapePointer(JSON_CONTENT_TYPE)}/schema`
  );
}

/** Turn `/api/teams/{teamId}/members` into `^/api/teams/[^/]+/members$`. */
function pathToRegex(rawPath: string): RegExp {
  const PARAM = " ";
  const withPlaceholders = rawPath.replace(/\{[^}]+\}/g, PARAM);
  const escaped = withPlaceholders.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`^${escaped.replace(new RegExp(PARAM, "g"), "[^/]+")}$`);
}

interface Route {
  regex: RegExp;
  staticSegments: number;
  pointerByMethod: Map<string, string>;
  /** Allowed `?key=` names per method. Present for every method the spec declares. */
  queryByMethod: Map<string, Set<string>>;
  /** Per method, a map of 2xx status -> response-schema pointer (JSON responses only). */
  responseByMethod: Map<string, Map<string, string>>;
}

/** A declared 2xx JSON response — the shape we validate mocked responses against. */
const SUCCESS_STATUS = /^2\d\d$/;

/** Pointer to the operation's JSON request-body schema, for the methods the backend validates. */
function requestBodyPointer(
  rawPath: string,
  method: string,
  op: Operation | undefined
): string | null {
  if (!ENFORCED_METHODS.has(method)) return null;
  if (!op?.requestBody?.content?.[JSON_CONTENT_TYPE]?.schema) return null;
  return pointerFor(rawPath, method);
}

/**
 * The operation's allowed `?key=` names. An operation with no `parameters` accepts no query
 * params — an empty set is the contract, not a missing one. FastAPI emits every param inline
 * at the operation level (verified: 0 $refs, 0 path-level `parameters`).
 */
function queryParamNames(op: Operation | undefined): Set<string> {
  const names = new Set<string>();
  for (const param of op?.parameters ?? []) {
    if (param.in === "query" && typeof param.name === "string") names.add(param.name);
  }
  return names;
}

/**
 * 2xx responses that declare a JSON body, as status -> schema pointer — a mock returning that
 * status is validated against this schema. Non-2xx (deliberate error mocks) is skipped.
 */
function successResponsePointers(
  rawPath: string,
  method: string,
  op: Operation | undefined
): Map<string, string> {
  const pointers = new Map<string, string>();
  for (const [status, resp] of Object.entries(op?.responses ?? {})) {
    if (!SUCCESS_STATUS.test(status)) continue;
    if (resp?.content?.[JSON_CONTENT_TYPE]?.schema) {
      pointers.set(status, pointerForResponse(rawPath, method, status));
    }
  }
  return pointers;
}

function buildRoute(rawPath: string, item: Record<string, Operation>): Route | null {
  const pointerByMethod = new Map<string, string>();
  const queryByMethod = new Map<string, Set<string>>();
  const responseByMethod = new Map<string, Map<string, string>>();
  for (const method of Object.keys(item)) {
    const op = item[method];
    const bodyPointer = requestBodyPointer(rawPath, method, op);
    if (bodyPointer) pointerByMethod.set(method, bodyPointer);
    if (!HTTP_METHODS.has(method)) continue;
    queryByMethod.set(method, queryParamNames(op));
    const responses = successResponsePointers(rawPath, method, op);
    if (responses.size > 0) responseByMethod.set(method, responses);
  }
  if (pointerByMethod.size === 0 && queryByMethod.size === 0 && responseByMethod.size === 0) {
    return null;
  }
  return {
    regex: pathToRegex(rawPath),
    staticSegments: rawPath.split("/").filter((s) => s.length > 0 && !s.includes("{")).length,
    pointerByMethod,
    queryByMethod,
    responseByMethod,
  };
}

function buildRoutes(): Route[] {
  const routes: Route[] = [];
  for (const [rawPath, item] of Object.entries(spec.paths)) {
    const route = buildRoute(rawPath, item);
    if (route) routes.push(route);
  }
  return routes;
}

const routes = buildRoutes();
const validatorCache = new Map<string, ValidateFunction | null>();

function getValidator(pointer: string): ValidateFunction | null {
  const cached = validatorCache.get(pointer);
  if (cached !== undefined) return cached;
  let validate: ValidateFunction | null;
  try {
    validate = (ajv.getSchema(pointer) as ValidateFunction | undefined) ?? null;
  } catch {
    validate = null; // unresolvable schema -> don't block the request
  }
  validatorCache.set(pointer, validate);
  return validate;
}

function stripTrailingSlash(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

/**
 * Most-specific match wins (static segments beat path params). `declares` picks
 * which table the route must appear in, so a path is only considered when it
 * actually carries the thing we're about to validate.
 */
function matchRoute(
  method: string,
  pathname: string,
  declares: (route: Route, method: string) => boolean
): Route | null {
  const m = method.toLowerCase();
  const normalized = stripTrailingSlash(pathname);
  let best: Route | null = null;
  for (const route of routes) {
    if (!declares(route, m) || !route.regex.test(normalized)) continue;
    if (best === null || route.staticSegments > best.staticSegments) best = route;
  }
  return best;
}

function matchPointer(method: string, pathname: string): string | null {
  const m = method.toLowerCase();
  if (!ENFORCED_METHODS.has(m)) return null;
  const route = matchRoute(m, pathname, (r, mm) => r.pointerByMethod.has(mm));
  return route?.pointerByMethod.get(m) ?? null;
}

function matchResponsePointer(method: string, pathname: string, status: string): string | null {
  const m = method.toLowerCase();
  if (!HTTP_METHODS.has(m)) return null;
  const route = matchRoute(m, pathname, (r, mm) => r.responseByMethod.has(mm));
  return route?.responseByMethod.get(m)?.get(status) ?? null;
}

function toCamelKey(key: string): string {
  return key.replace(/[_-]+([a-zA-Z0-9])/g, (_match, char: string) => char.toUpperCase());
}

/**
 * Recursively camelCase object keys. The backend accepts both snake_case and
 * camelCase (`validate_by_name=True`), but the spec only lists camelCase aliases
 * with `additionalProperties:false`. Normalizing mirrors that dual acceptance so
 * a service that legitimately sends snake_case isn't flagged — while a genuinely
 * unknown field (`foo`) stays unknown and is still caught. Operates on a clone.
 *
 * Applied as a FALLBACK, never as a precondition — see `validateRequest`.
 * Opaque dict passthroughs (e.g. the snake_case storage keys inside
 * `newPersona.prospectCriteria`) are mangled by this, which is another reason
 * the as-authored attempt runs first.
 */
function camelizeKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(camelizeKeys);
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[toCamelKey(k)] = camelizeKeys(v);
    }
    return out;
  }
  return value;
}

function joinField(base: string, leaf: string): string {
  return base.length > 0 ? `${base}.${leaf}` : leaf;
}

function describeError(err: ErrorObject): ContractError {
  const params = err.params as Record<string, unknown>;
  let field = err.instancePath.replace(/^\//, "").replace(/\//g, ".");
  if (err.keyword === "additionalProperties" && typeof params["additionalProperty"] === "string") {
    field = joinField(field, params["additionalProperty"]);
  } else if (err.keyword === "required" && typeof params["missingProperty"] === "string") {
    field = joinField(field, params["missingProperty"]);
  }
  return {
    field: field.length > 0 ? field : "(body)",
    keyword: err.keyword,
    message: err.message ?? "is invalid",
  };
}

/**
 * Validate a request body against the backend contract.
 * Returns `null` when the request is fine OR not contract-enforced (unknown
 * path, non-mutating method, or no JSON request body for the operation).
 *
 * Two attempts, because the backend accepts either spelling per field
 * (`validate_by_name=True`) even though every schema — LLM tool-arg schemas
 * included, since the casing exemption closed — is camelCase in the spec:
 *
 *  1. **As authored.** The canonical path: a correct camelCase body passes
 *     here, and opaque dict passthroughs (snake_case storage keys inside e.g.
 *     `prospectCriteria`) are left intact rather than mangled.
 *  2. **Camelized.** Covers a service sending snake_case at a camelCase-aliased
 *     field, which the backend takes but the spec doesn't list.
 *
 * A genuinely unknown field (`foo`) survives both and is still caught.
 */
export function validateRequest(
  method: string,
  pathname: string,
  body: unknown
): ContractViolation | null {
  const pointer = matchPointer(method, pathname);
  if (pointer === null) return null;
  const validate = getValidator(pointer);
  if (validate === null) return null;

  if (validate(body)) return null;
  // Capture before the next call — Ajv overwrites `errors` on each invocation.
  const rawErrors = validate.errors ?? [];

  if (validate(camelizeKeys(body))) return null;
  const camelErrors = validate.errors ?? [];

  // Both readings failed, so the payload is genuinely broken. Report whichever
  // diagnosed it more tightly: against a snake_case schema the camelized attempt
  // invents "missing job_titles/min_employee_count/…" noise on top of the real
  // error, and against a camelCase one the raw attempt does the mirror image.
  // Fewer errors is the better proxy for the reading the backend would have
  // taken; ties go to the body as the caller actually wrote it.
  const errors = camelErrors.length < rawErrors.length ? camelErrors : rawErrors;
  return {
    kind: "body",
    method: method.toUpperCase(),
    path: pathname,
    errors: errors.map(describeError),
  };
}

/**
 * Validate outgoing query params against the operation's declared `parameters`.
 *
 * The gap this closes: FastAPI's `Query` args are not a Pydantic mechanism, so
 * the camelCase generator never touched them and the body validator above never
 * looked at them. Worse, FastAPI query aliases are alias-*only* — a request
 * carrying a retired `?page_size=7` doesn't 422, it silently falls back to the
 * default and returns a plausible page of the wrong size. Nothing in the suite
 * caught that class of bug before.
 *
 * Unknown-key only: missing-but-required is deliberately not enforced, because
 * tests legitimately exercise partial filter states.
 *
 * Returns `null` when fine, or when the route/method isn't in the spec at all
 * (unmatched path, external host) — same fail-open posture as the body check.
 */
export function validateQueryParams(
  method: string,
  pathname: string,
  searchParams: URLSearchParams
): ContractViolation | null {
  const m = method.toLowerCase();
  if (!HTTP_METHODS.has(m)) return null;
  const route = matchRoute(m, pathname, (r, mm) => r.queryByMethod.has(mm));
  const allowed = route?.queryByMethod.get(m);
  if (allowed === undefined) return null;

  const errors: ContractError[] = [];
  for (const key of new Set(searchParams.keys())) {
    if (allowed.has(key)) continue;
    // The overwhelmingly likely cause is a retired snake_case name, so say so
    // outright rather than making the reader diff two lists by eye.
    const camel = toCamelKey(key);
    const hint = camel !== key && allowed.has(camel) ? ` — renamed to \`${camel}\`` : "";
    errors.push({
      field: key,
      keyword: "unknownQueryParam",
      message: `is not a query parameter of this operation${hint}`,
    });
  }
  if (errors.length === 0) return null;
  return { kind: "query", method: method.toUpperCase(), path: pathname, errors };
}

/**
 * Validate a mocked response body against the backend's declared 2xx response
 * schema. This is what makes the MSW boundary trustworthy: a handler returning a
 * shape the backend can't produce (a missing required field, a renamed field, a
 * wrong type) fails here instead of silently certifying a contract that drifted.
 *
 * Single pass — responses are camelCase, so no snake/camel dual attempt. Enforces
 * required fields + types, NOT unknown fields: `*Out` schemas use Pydantic
 * `extra="ignore"` (no `additionalProperties:false`), so an extra mock field is
 * tolerated exactly as the backend tolerates it.
 *
 * Returns `null` when fine, or when there's nothing to check — unmatched path,
 * non-2xx status, or a 2xx with no declared JSON schema (same fail-open posture
 * as the request validators).
 */
export function validateResponse(
  method: string,
  pathname: string,
  status: number,
  body: unknown
): ContractViolation | null {
  const pointer = matchResponsePointer(method, pathname, String(status));
  if (pointer === null) return null;
  const validate = getValidator(pointer);
  if (validate === null) return null;

  if (validate(body)) return null;
  const errors = validate.errors ?? [];
  return {
    kind: "response",
    method: method.toUpperCase(),
    path: pathname,
    errors: errors.map(describeError),
  };
}

export function formatViolation(violation: ContractViolation): string {
  const lines = violation.errors.map((e) => {
    let hint = "";
    if (e.keyword === "additionalProperties") {
      hint = " — field not accepted by the backend schema";
    } else if (violation.kind === "response" && e.keyword === "required") {
      hint = " — field required by the backend response schema (fix the mock)";
    }
    return `      • ${e.field}: ${e.message}${hint}`;
  });
  const label =
    violation.kind === "response" ? " (response)" : violation.kind === "query" ? " (query)" : "";
  return `    ${violation.method} ${violation.path}${label}\n${lines.join("\n")}`;
}
