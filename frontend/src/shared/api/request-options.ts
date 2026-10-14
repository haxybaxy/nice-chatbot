/**
 * Request plumbing shared by the two transports — `apiClient` (JSON, axios) and the SSE client
 * (`services/sse-client.ts`, fetch). Both take a spec path plus `path` / `query` options whose
 * types the generated OpenAPI types decide; this module holds those option types and the path
 * substitution so the two clients cannot drift apart.
 */
import type { HttpMethod, PathParams, PathsWith, QueryParams } from "./types";

/** `path` is required exactly when the operation has `{segments}`. */
export type PathOption<P extends PathsWith<M>, M extends HttpMethod> = [PathParams<P, M>] extends [
  never,
]
  ? { path?: undefined }
  : { path: PathParams<P, M> };

/** `query` exists only when the operation declares query params; optional when all of them are. */
export type QueryOption<P extends PathsWith<M>, M extends HttpMethod> = [
  QueryParams<P, M>,
] extends [never]
  ? { query?: undefined }
  : object extends QueryParams<P, M>
    ? { query?: QueryParams<P, M> }
    : { query: QueryParams<P, M> };

/** The type-erased view of `path` / `query` that the transports work with at runtime. */
export interface RuntimeRequestOptions {
  path?: Record<string, string>;
  query?: Record<string, unknown>;
}

/** Replace every `{name}` in a spec path with its encoded value. */
export function substitutePathParams(
  path: string,
  params: Record<string, string> | undefined
): string {
  return path.replace(/\{([^}]+)\}/g, (_match, name: string) => {
    const value = params?.[name];
    if (value === undefined) {
      throw new Error(`Missing path parameter "${name}" for ${path}`);
    }
    return encodeURIComponent(value);
  });
}
