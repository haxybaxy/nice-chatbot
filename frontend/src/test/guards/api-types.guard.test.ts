/**
 * Pins the type helpers in `@/shared/api/types` to the generated spec. Pure type assertions:
 * `expectTypeOf` is a runtime no-op that `tsc` checks (`just typecheck`), so this file is the
 * regression net for an openapi-typescript upgrade changing the `?: never` emission the
 * helpers rely on, or for a helper edit that silently widens a signature.
 */
import { describe, expectTypeOf, it } from "vitest";

import type {
  BodylessPaths,
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
      | "/api/health"
      | "/api/health/ready"
      | "/api/organizations/{organization_id}"
      | "/api/organizations/{organization_id}/members"
      | "/api/users/me"
    >();
    expectTypeOf<PathsWith<"patch">>().toEqualTypeOf<"/api/users/me">();
    expectTypeOf<PathsWith<"put">>().toEqualTypeOf<never>();
    // No DELETE takes a body today; if one ever does, `apiClient.delete` will refuse it.
    expectTypeOf<BodylessPaths<"delete">>().toEqualTypeOf<PathsWith<"delete">>();
  });
});
