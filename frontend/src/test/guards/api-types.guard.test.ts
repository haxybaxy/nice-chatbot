/**
 * Pins the type helpers in `@/shared/api/types` to the generated spec. Pure type assertions:
 * `expectTypeOf` is a runtime no-op that `tsc` checks (`just typecheck`), so this file is the
 * regression net for an openapi-typescript upgrade changing the `?: never` emission the
 * helpers rely on, or for a helper edit that silently widens a signature.
 */
import { describe, expectTypeOf, it } from "vitest";

import type {
  BodylessPaths,
  FormBody,
  FormPaths,
  JsonPaths,
  PathParams,
  PathsWith,
  QueryParams,
  RequestBody,
  Schema,
  SuccessBody,
} from "@/shared/api/types";

describe("generated API type helpers", () => {
  it("derives the request body from the operation, `never` when it has none", () => {
    expectTypeOf<RequestBody<"/api/auth/signup", "post">>().toEqualTypeOf<Schema<"SignUpIn">>();
    expectTypeOf<RequestBody<"/api/auth/refresh", "post">>().toEqualTypeOf<Schema<"RefreshIn">>();
    expectTypeOf<RequestBody<"/api/users/me", "patch">>().toEqualTypeOf<Schema<"UpdateUserIn">>();
    expectTypeOf<RequestBody<"/api/auth/signout", "post">>().toEqualTypeOf<never>();
    expectTypeOf<RequestBody<"/api/users/me", "get">>().toEqualTypeOf<never>();
  });

  it("derives the success body from every 2xx response, `undefined` for a 204", () => {
    expectTypeOf<SuccessBody<"/api/auth/signup", "post">>().toEqualTypeOf<Schema<"SignUpOut">>();
    expectTypeOf<SuccessBody<"/api/auth/signin", "post">>().toEqualTypeOf<Schema<"TokensOut">>();
    expectTypeOf<SuccessBody<"/api/users/me", "get">>().toEqualTypeOf<Schema<"UserOut">>();
    expectTypeOf<
      SuccessBody<"/api/organizations/{organization_id}/members", "get">
    >().toEqualTypeOf<Schema<"OrganizationMemberOut">[]>();
    expectTypeOf<SuccessBody<"/api/auth/signout", "post">>().toEqualTypeOf<undefined>();
    expectTypeOf<SuccessBody<"/api/users/me", "delete">>().toEqualTypeOf<undefined>();
  });

  it("derives path and query params, `never` when the operation declares none", () => {
    expectTypeOf<
      PathParams<"/api/organizations/{organization_id}/members", "get">
    >().toEqualTypeOf<{ organization_id: string }>();
    expectTypeOf<
      PathParams<"/api/organizations/{organization_id}/members/{user_id}", "delete">
    >().toEqualTypeOf<{ organization_id: string; user_id: string }>();
    expectTypeOf<PathParams<"/api/users/me", "get">>().toEqualTypeOf<never>();
    expectTypeOf<QueryParams<"/api/users/me", "get">>().toEqualTypeOf<never>();
  });

  it("lists the paths per verb from the generator's `?: never` emission", () => {
    expectTypeOf<PathsWith<"get">>().toEqualTypeOf<
      | "/api/attachments/{attachment_id}"
      | "/api/attachments/{attachment_id}/content"
      | "/api/chat/models"
      | "/api/conversations/{conversation_id}"
      | "/api/conversations/{conversation_id}/runs/active"
      | "/api/conversations/{conversation_id}/runs/{run_id}"
      | "/api/conversations/{conversation_id}/runs/{run_id}/events"
      | "/api/health"
      | "/api/health/ready"
      | "/api/organizations/{organization_id}"
      | "/api/organizations/{organization_id}/members"
      | "/api/teams"
      | "/api/teams/{team_id}"
      | "/api/teams/{team_id}/conversations"
      | "/api/teams/{team_id}/members"
      | "/api/users/me"
    >();
    expectTypeOf<PathsWith<"patch">>().toEqualTypeOf<
      "/api/conversations/{conversation_id}" | "/api/users/me"
    >();
    expectTypeOf<PathsWith<"put">>().toEqualTypeOf<never>();
    // No DELETE takes a body today; if one ever does, `apiClient.delete` will refuse it.
    expectTypeOf<BodylessPaths<"delete">>().toEqualTypeOf<PathsWith<"delete">>();
  });

  it("separates the multipart operation from the JSON ones", () => {
    const UPLOAD = "/api/teams/{team_id}/attachments";
    expectTypeOf<FormPaths<"post">>().toEqualTypeOf<typeof UPLOAD>();
    expectTypeOf<FormPaths<"get">>().toEqualTypeOf<never>();
    expectTypeOf<FormBody<typeof UPLOAD, "post">>().toEqualTypeOf<
      Schema<"Body_upload_attachment_api_teams__team_id__attachments_post">
    >();
    expectTypeOf<FormBody<"/api/auth/signup", "post">>().toEqualTypeOf<never>();
    // The upload has no JSON body, yet it is neither a JSON path nor a bodyless one: only
    // `apiClient.upload` accepts it.
    expectTypeOf<RequestBody<typeof UPLOAD, "post">>().toEqualTypeOf<never>();
    expectTypeOf<Extract<JsonPaths<"post">, typeof UPLOAD>>().toEqualTypeOf<never>();
    expectTypeOf<Extract<BodylessPaths<"post">, typeof UPLOAD>>().toEqualTypeOf<never>();
    expectTypeOf<SuccessBody<typeof UPLOAD, "post">>().toEqualTypeOf<Schema<"AttachmentOut">>();
    expectTypeOf<
      QueryParams<"/api/attachments/{attachment_id}/content", "get">
    >().toEqualTypeOf<{ download?: boolean }>();
  });
});
