import { http, type HttpResponseResolver, type PathParams as MswPathParams } from "msw";

import type {
  ApiPath,
  HttpMethod,
  PathParams,
  PathsWith,
  RequestBody,
  Schema,
  SuccessBody,
} from "@/shared/api/types";
import { API_ENDPOINTS } from "@/shared/config/api-endpoints";

const BASE = API_ENDPOINTS.EXTERNAL.BACKEND;

/**
 * Absolute URL for a spec path in MSW's `:param` syntax:
 * `/api/organizations/{organization_id}` -> `http://…/api/organizations/:organization_id`.
 */
function url(path: ApiPath): string {
  return `${BASE}${path.replace(/\{([^}]+)\}/g, ":$1")}`;
}

/** Our `{ organization_id: string }` (or `never`) in the shape MSW's `Params` generic expects. */
type Params<P extends PathsWith<M>, M extends HttpMethod> = [PathParams<P, M>] extends [never]
  ? MswPathParams<never>
  : PathParams<P, M>;

/** A handler may answer with the operation's 2xx body or the one error envelope. */
type ResponseBody<P extends PathsWith<M>, M extends HttpMethod> =
  SuccessBody<P, M> | Schema<"ErrorOut">;

type SpecResolver<P extends PathsWith<M>, M extends HttpMethod> = HttpResponseResolver<
  Params<P, M>,
  RequestBody<P, M>,
  ResponseBody<P, M>
>;

type Verb = "get" | "post" | "patch" | "delete";

function forVerb<M extends Verb>(method: M) {
  return <P extends PathsWith<M>>(path: P, resolver: SpecResolver<P, M>) =>
    http[method]<Params<P, M>, RequestBody<P, M>, ResponseBody<P, M>>(url(path), resolver);
}

/**
 * Spec-typed MSW handlers: `mockApi.post(API_ENDPOINTS.AUTH.SIGNUP, resolver)`.
 *
 * Inside the resolver `request.json()` is the operation's `*In` schema, `params` are the path's
 * `{segments}`, and `HttpResponse.json(...)` must be its `*Out` schema or an `ErrorOut`
 * (`errorResponse()` in `fixtures/error.ts`). A thin wrapper over
 * `http.<verb><Params, RequestBody, ResponseBody>(url(path), …)` so no handler spells those
 * three generics by hand — the path + verb derive them from the generated types.
 */
export const mockApi = {
  get: forVerb("get"),
  post: forVerb("post"),
  patch: forVerb("patch"),
  delete: forVerb("delete"),
};
